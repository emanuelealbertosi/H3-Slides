"""Logical paragraph breaks are editorial guidance, not another content budget."""
import pytest

from h3_slides.content_rules import (
    content_contract, fit_complete_sentences, paragraph_budget, validate_content,
)
from h3_slides.models import ProjectInput, SlideContent


@pytest.mark.parametrize('density', ['detailed', 'complete'])
@pytest.mark.parametrize('visual', [False, True])
@pytest.mark.parametrize('count', [None, 1, 2, 3, 4])
def test_capoversi_guidance_is_generic_and_preserves_the_existing_budget(density, visual, count):
    project = ProjectInput(text_density=density, use_manim_diagrams=visual).model_dump()
    schema, rules = content_contract(project, count)
    base = paragraph_budget(project)
    maximum = min(base, base * 2 // count) if count else base
    assert schema['$defs']['TextBlock']['properties']['text']['maxLength'] == maximum + 120
    assert schema['properties']['blocks']['minItems'] == (count or 1)
    assert schema['properties']['blocks']['maxItems'] == (count or 4)
    assert schema['properties']['bullets']['maxItems'] == 0
    assert f'massimo {base * 2} caratteri' in rules
    assert 'quando utile' in rules and '2–3 capoversi logici' in rules
    assert r'\n\n' in rules
    assert 'Mantieni contenuti e budget complessivo' in rules
    assert 'senza tagliare spiegazioni' in rules
    assert 'né trasformarle automaticamente in elenchi' in rules
    assert 'solo la prosa: non riscrivere codice, citazioni letterali o formule' in rules
    assert 'e un paragrafo di' not in rules


def test_brief_mode_does_not_require_capoversi():
    schema, rules = content_contract(ProjectInput(text_density='brief').model_dump())
    assert 'capoversi' not in rules
    assert schema['properties']['bullets']['maxItems'] == 3


@pytest.mark.parametrize('kind', ['code', 'quote', 'key'])
def test_existing_newlines_and_literal_code_quotes_math_are_not_rewritten(kind):
    prose = ('Il primo capoverso introduce un concetto e ne chiarisce lo scopo nella spiegazione.\n\n'
             'Il secondo descrive un esempio concreto e collega le sue conseguenze al concetto iniziale.')
    literal = {
        'code': 'def quadrato(numero):\n    return numero * numero\n\nprint(quadrato(4))',
        'quote': ('Un brano originale mantiene il significato e la struttura della fonte consultata.\n\n'
                  'Anche il secondo capoverso deve essere conservato esattamente come nel documento.'),
        'key': r'\(f(x)=x^2\)' + '\n\n' + r'\[f\prime(x)=2x\]',
    }[kind]
    project = ProjectInput(text_density='complete').model_dump()
    project['sources'] = [{'name': 'fonte.md'}] if kind == 'quote' else []
    source = 'fonte.md, p. 2' if kind == 'quote' else ''
    content = SlideContent(title='Struttura leggibile', blocks=[
        {'heading': 'Spiegazione', 'text': prose},
        {'heading': 'Passaggio', 'kind': kind, 'language': 'python' if kind == 'code' else 'text',
         'text': literal, 'source': source},
    ])
    original = [block.text for block in content.blocks]
    validate_content(content, project, f'[{source}]\n{literal}' if source else '')
    assert not fit_complete_sentences(content, project)
    assert [block.text for block in content.blocks] == original
