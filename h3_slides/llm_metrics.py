"""Content-free LLM timings; wall-clock throughput is not decode speed."""
import math


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _number(value):
    if type(value) not in (int, float):
        return None
    try:
        return value if math.isfinite(value) and value >= 0 else None
    except (OverflowError, ValueError):
        return None


def _rate(tokens, seconds):
    if tokens is None or seconds is None or seconds <= 0:
        return None
    return _number(tokens / seconds)


def completion_metrics(result, elapsed_seconds):
    """Whitelist numeric fields only; never return arbitrary provider data."""
    result = _mapping(result)
    usage = _mapping(result.get("usage"))
    stats = _mapping(result.get("stats"))
    timings = _mapping(result.get("timings"))
    details = _mapping(usage.get("completion_tokens_details"))
    prompt_details = _mapping(usage.get("prompt_tokens_details"))
    elapsed = _number(elapsed_seconds)
    output = _number(usage.get("completion_tokens"))
    prefill_tokens = _number(timings.get("prompt_n"))
    decode_tokens = _number(timings.get("predicted_n"))
    cached_tokens = _number(prompt_details.get("cached_tokens"))
    if cached_tokens is None:
        cached_tokens = _number(timings.get("cache_n"))
    native_tps = _number(stats.get("tokens_per_second"))
    if native_tps is None:
        native_tps = _number(timings.get("predicted_per_second"))
    generation = _number(stats.get("generation_time"))
    if generation is None:
        milliseconds = _number(timings.get("predicted_ms"))
        generation = milliseconds / 1000 if milliseconds is not None else None
    prefill_ms = _number(timings.get("prompt_ms"))
    prefill_seconds = prefill_ms / 1000 if prefill_ms is not None else None
    prefill_tps = _number(timings.get("prompt_per_second"))
    if prefill_tps is None:
        # prompt_tokens is the entire context, including cache hits. Only the
        # server's actual prefill count can yield a meaningful prefill rate.
        prefill_tps = _rate(prefill_tokens, prefill_seconds)
    # Do not derive decode speed from predicted_n / predicted_ms. Servers may
    # count the first token in prefill and use a different decode numerator.
    wall_tps = _rate(output, elapsed)
    choices = result.get("choices")
    choice = _mapping(choices[0]) if isinstance(choices, list) and choices else {}
    finish = choice.get("finish_reason")
    if finish not in ("stop", "length", "tool_calls", "function_call", "content_filter", None):
        finish = "other"
    return {
        "request_seconds": round(elapsed, 3) if elapsed is not None else None,
        "input_tokens": _number(usage.get("prompt_tokens")),
        "output_tokens": output,
        "reasoning_tokens": _number(details.get("reasoning_tokens")),
        "input_cached_tokens": cached_tokens,
        "end_to_end_output_tokens_per_second": round(wall_tps, 2) if wall_tps is not None else None,
        "server_prefill_tokens": prefill_tokens,
        "server_decode_tokens": decode_tokens,
        "server_prefill_tokens_per_second": prefill_tps,
        "server_decode_tokens_per_second": native_tps,
        "server_ttft_seconds": _number(stats.get("time_to_first_token")),
        "server_generation_seconds": generation,
        "server_prefill_seconds": prefill_seconds,
        "finish": finish,
    }


def local_performance_message(metrics, request_number):
    """One content-free local progress line; missing telemetry is never zero."""
    metrics = _mapping(metrics)

    def amount(value, unit, decimals=None):
        number = _number(value)
        if number is None:
            return "n.d."
        formatted = format(number, "g" if decimals is None else f".{decimals}f")
        return formatted + unit

    request = amount(request_number, "")
    decoded = _number(metrics.get("server_decode_tokens"))
    if decoded is None:
        # Usage counts can label visible output, but never manufacture a native
        # decode rate or substitute total context tokens for actual prefill work.
        decoded = _number(metrics.get("output_tokens"))
    prefill = " · ".join((amount(metrics.get("server_prefill_tokens"), " token"),
        amount(metrics.get("server_prefill_seconds"), "s", 3),
        amount(metrics.get("server_prefill_tokens_per_second"), " token/s", 2)))
    generation = " · ".join((amount(decoded, " token"),
        amount(metrics.get("server_generation_seconds"), "s", 3),
        amount(metrics.get("server_decode_tokens_per_second"), " token/s", 2)))
    line = (f"LLM interno #{request} · Prefill: {prefill} | Generazione: {generation} | "
            f"Cache input: {amount(metrics.get('input_cached_tokens'), ' token')} | "
            f"Totale richiesta: {amount(metrics.get('request_seconds'), 's', 3)}")
    outcome = metrics.get("outcome")
    errors = {"error": "errore", "timeout": "timeout", "connection_error": "errore di connessione",
              "cancelled": "annullata"}
    if isinstance(outcome, str) and outcome in errors:
        line += " | Esito: " + errors[outcome]
    attempts = _number(metrics.get("attempts"))
    if attempts is not None and attempts > 1 and int(attempts) == attempts:
        line += " | Tentativi: " + str(int(attempts))
    return line
