"""A bounded scene language compiled into real Manim objects, never Python eval."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .math_expression import validate_expression, function_line

Number = Annotated[float, Field(ge=-1e9, le=1e9, allow_inf_nan=False)]
Tone = Literal["accent", "blue", "amber", "red", "violet", "neutral"]


class FunctionCurve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expression: str = Field(min_length=1, max_length=120)
    label: str = Field(default="", max_length=36)
    tone: Tone = "blue"
    asymptotes: list[Number] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def safe_curve(self):
        self.expression = validate_expression(self.expression)
        return self


class Element(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,31}$")
    type: Literal["box", "decision", "circle", "database", "document", "text",
                  "grid", "bars", "plot", "function_plot", "venn", "gantt", "timeline", "tree", "network"]
    x: float = Field(ge=.2, le=11.8, allow_inf_nan=False)
    y: float = Field(ge=1.1, le=7.2, allow_inf_nan=False)
    width: float = Field(default=2.8, ge=.6, le=11, allow_inf_nan=False)
    height: float = Field(default=1.2, ge=.5, le=6, allow_inf_nan=False)
    text: str = Field(default="", max_length=80)
    caption: str = Field(default="", max_length=90)
    tone: Tone = "accent"
    stage: int = Field(default=1, ge=1, le=12)
    values: list[Number] = Field(default_factory=list, max_length=64)
    labels: list[Annotated[str, Field(max_length=18)]] = Field(default_factory=list, max_length=16)
    columns: int = Field(default=4, ge=1, le=8)
    expression: str = Field(default="", max_length=120)
    x_min: Number = -5
    x_max: Number = 5
    y_min: Number = -5
    y_max: Number = 5
    asymptotes: list[Number] = Field(default_factory=list, max_length=8)
    series: list[FunctionCurve] = Field(default_factory=list, max_length=3)
    tangent_at: Number | None = None
    secant_x: list[Number] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def geometry_and_data(self):
        if self.x-self.width/2 < .15 or self.x+self.width/2 > 11.85 or self.y-self.height/2 < 1.05 or self.y+self.height/2 > 7.25:
            raise ValueError(f"Elemento {self.id}: ingombro fuori dal canvas utile x=0.15..11.85, y=1.05..7.25")
        if self.type in ("grid", "bars", "plot") and not self.values:
            raise ValueError(f"Elemento {self.id}: servono dati numerici reali o un esempio esplicitamente illustrativo")
        if self.type == "grid" and (len(self.values) % self.columns or any(not 0 <= v <= 1 for v in self.values)):
            raise ValueError(f"Griglia {self.id}: values tra 0 e 1, numero multiplo di columns")
        if self.type == "bars" and (len(self.values) > 8 or any(v < 0 for v in self.values) or max(self.values) == 0):
            raise ValueError(f"Barre {self.id}: da 1 a 8 valori non negativi, almeno uno positivo")
        if self.type == "plot" and len(self.values) < 2:
            raise ValueError(f"Grafico {self.id}: servono almeno due campioni")
        if self.type == "function_plot":
            self.expression = validate_expression(self.expression)
            if not self.x_min < self.x_max or not self.y_min < self.y_max:
                raise ValueError(f"Funzione {self.id}: gli intervalli degli assi devono essere crescenti")
            self.asymptotes = sorted(set(self.asymptotes))
            if any(not self.x_min < value < self.x_max for value in self.asymptotes):
                raise ValueError(f"Funzione {self.id}: gli asintoti verticali devono essere interni al dominio")
            for curve in self.series:
                if any(not self.x_min < value < self.x_max for value in curve.asymptotes):
                    raise ValueError(f"Funzione {self.id}: asintoti della serie fuori dal dominio")
            if self.tangent_at is not None:
                if not self.x_min < self.tangent_at < self.x_max:
                    raise ValueError("Tangente: il punto deve essere interno al dominio")
                function_line(self.expression, self.tangent_at)
            if self.secant_x:
                if len(self.secant_x) != 2 or any(not self.x_min <= x <= self.x_max for x in self.secant_x):
                    raise ValueError("Secante: servono due ascisse nel dominio")
                function_line(self.expression, *self.secant_x)
        elif self.series or self.tangent_at is not None or self.secant_x:
            raise ValueError("series, tangent_at e secant_x appartengono a function_plot, non ai grafici a campioni")
        if self.type == "bars" and len(self.labels) != len(self.values):
            raise ValueError(f"Barre {self.id}: ogni valore richiede un'etichetta")
        if self.type == "venn" and not 2 <= len(self.labels) <= 4:
            raise ValueError(f"Venn {self.id}: servono da 2 a 4 insiemi in labels")
        if self.type == "gantt":
            if not 1 <= len(self.labels) <= 8 or len(self.values) != len(self.labels)*2:
                raise ValueError(f"Gantt {self.id}: labels contiene le attività e values le coppie inizio,fine")
            if any(self.values[i] >= self.values[i+1] for i in range(0, len(self.values), 2)):
                raise ValueError(f"Gantt {self.id}: ogni fine deve essere maggiore dell'inizio")
        if self.type == "timeline":
            if not 2 <= len(self.labels) <= 8:
                raise ValueError(f"Timeline {self.id}: servono da 2 a 8 eventi")
            if self.values and (len(self.values) != len(self.labels) or
                                any(a >= b for a, b in zip(self.values, self.values[1:]))):
                raise ValueError(f"Timeline {self.id}: values deve contenere una posizione crescente per evento")
        if self.type == "tree":
            if not 3 <= len(self.labels) <= 9 or len(self.values) != len(self.labels)-1:
                raise ValueError(f"Albero {self.id}: labels contiene i nodi e values il genitore di ogni nodo dopo la radice")
            if any(not value.is_integer() or value < 0 or value >= child
                   for child, value in enumerate(self.values, start=1)):
                raise ValueError(f"Albero {self.id}: ogni indice genitore deve essere intero e precedere il figlio")
            depths = [0]
            for parent in self.values:
                depths.append(depths[int(parent)]+1)
            if max(depths) > 3:
                raise ValueError(f"Albero {self.id}: massimo quattro livelli per mantenere il testo leggibile")
        if self.type == "network":
            if not 3 <= len(self.labels) <= 8 or len(self.values) < 2 or len(self.values) % 2:
                raise ValueError(f"Rete {self.id}: labels contiene i nodi e values le coppie di indici collegate")
            pairs = zip(self.values[::2], self.values[1::2])
            if any(not a.is_integer() or not b.is_integer() or a == b or
                   a < 0 or b < 0 or a >= len(self.labels) or b >= len(self.labels) for a, b in pairs):
                raise ValueError(f"Rete {self.id}: gli archi devono usare indici di nodi validi e distinti")
        if self.type in ("function_plot", "venn", "gantt", "timeline", "tree", "network") and (
                self.width < 5 or self.height < 3):
            raise ValueError(f"Diagramma {self.id}: usa width>=5 e height>=3")
        if self.type in ("gantt", "tree") and self.height < 4:
            raise ValueError(f"{self.type} {self.id}: usa height>=4")
        if self.type not in ("grid", "bars", "plot", "function_plot", "venn", "gantt", "timeline", "tree", "network") and not self.text.strip():
            raise ValueError(f"Elemento {self.id}: testo mancante")
        return self


class Connection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(max_length=32)
    target: str = Field(max_length=32)
    label: str = Field(default="", max_length=34)
    tone: Tone = "neutral"


class ManimSceneSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=75)
    takeaway: str = Field(default="", max_length=130)
    elements: list[Element] = Field(min_length=1, max_length=14)
    connections: list[Connection] = Field(default_factory=list, max_length=22)

    @model_validator(mode="after")
    def readable_scene(self):
        ids = [e.id for e in self.elements]
        if len(ids) != len(set(ids)):
            raise ValueError("Gli ID degli elementi devono essere unici")
        for edge in self.connections:
            if edge.source not in ids or edge.target not in ids or edge.source == edge.target:
                raise ValueError("Collegamento con estremi mancanti o identici")
        for index, a in enumerate(self.elements):
            for b in self.elements[index+1:]:
                if abs(a.x-b.x) < (a.width+b.width)/2+.08 and abs(a.y-b.y) < (a.height+b.height)/2+.08:
                    raise ValueError(f"Elementi sovrapposti o troppo vicini: {a.id}, {b.id}. Ridisponili con almeno 0.1 unità di spazio.")
        return self


def legacy_scene(diagram):
    """Render old saved data faithfully; only an explicit AI redesign adds meaning."""
    labels = diagram.get("labels", [])
    if len(labels) < 2:
        raise ValueError("Il diagramma non contiene ancora una scena: usa Progetta diagramma")
    n = len(labels)
    if diagram["kind"] == "cycle":
        import math
        positions = [(6+3.8*math.cos(-math.pi/2+2*math.pi*i/n),
                      4.15+2.1*math.sin(-math.pi/2+2*math.pi*i/n)) for i in range(n)]
    else:
        positions = [(3 if i % 2 == 0 else 9, 2+(i//2)*1.85) for i in range(n)]
    def legacy_type(index, text):
        lowered = text.casefold()
        if "?" in text or any(word in lowered for word in ("condizione", "trova", "verifica")):
            return "decision"
        if diagram["kind"] == "flow" and index in (0, n-1):
            return "circle"
        if diagram["kind"] == "cycle":
            return "circle"
        return "box"
    elements = [Element(id=f"n{i}", type=legacy_type(i, text), x=x, y=y, width=3, height=1.3,
                        text=text, stage=i+1) for i, ((x, y), text) in enumerate(zip(positions, labels))]
    connections = [] if diagram["kind"] == "comparison" else [
        Connection(source=f"n{i}", target=f"n{(i+1)%n}") for i in range(n if diagram["kind"] == "cycle" else n-1)]
    return ManimSceneSpec(title="Diagramma", elements=elements, connections=connections)


SCENE_PROMPT = """PROGETTA UNA SCENA MANIM, non una slide di testo e non una lista di scatole.
Il disegno deve spiegare un meccanismo, una struttura o dati concreti presenti nella slide.
Non inventare misurazioni. Per esempi numerici inventati a scopo didattico scrivi 'Esempio illustrativo'.
Scegli il linguaggio visivo pertinente: decision per condizioni e rami sì/no; database per archivi;
document per file; circle per entità; grid per pixel/matrici (valori 0..1); bars per confronti quantitativi
(labels per ogni valore); plot per segnali/campioni; function_plot per il grafico cartesiano di una funzione;
venn per 2–4 insiemi sovrapposti (nomi in labels);
gantt per attività temporali (labels e coppie inizio,fine in values); timeline per eventi ordinati
(labels e posizioni crescenti facoltative in values); tree per gerarchie (labels e indice del genitore
di ogni nodo dopo la radice in values); network per grafi (labels e coppie di indici collegate in values).
values accetta ESCLUSIVAMENTE numeri JSON, mai formule, parole, null, unità o valori come "O(n)".
Per function_plot usa expression con la sola variabile x, numeri, + - * / ^ e le funzioni
sin, cos, tan, sqrt, log, ln, exp, abs; imposta x_min,x_max,y_min,y_max e gli eventuali
asintoti verticali in asymptotes. Per y=1/x usa expression "1/x" e asymptotes [0]:
il motore traccia deterministicamente due rami separati. Non scrivere codice Python.
Per confrontare funzioni sugli STESSI ASSI, usa UN function_plot: expression per la funzione principale,
series per fino a 3 curve aggiuntive, ciascuna con expression, label, tone e asymptotes.
Per secante e tangente NON usare plot senza values: imposta tangent_at con l'ascissa di tangenza
e secant_x con le due ascisse della secante sullo stesso function_plot. Il motore calcola le rette.
Esempio illustrativo: expression "x^2", tangent_at 1, secant_x [1,2],
x_min -1,x_max 3,y_min -3,y_max 9,width 10,height 5.8. Non inventare campioni delle rette.
Per confrontare grafici con assi DIVERSI, usa due function_plot affiancati con width=5.4,
height=5.5,x=3 e x=9,y=4.15. Non sovrapporre pannelli distinti.
Usa un elemento composto function_plot/venn/gantt/timeline/tree/network grande almeno width=5,height=3
(Gantt height>=4), anziché approssimarlo con riquadri. Non forzare grafici numerici su argomenti senza dati.
Tu progetti elementi e relazioni, Manim costruisce e renderizza la scena.
Canvas 12 × 8, x cresce verso destra e y verso il basso. x,y sono il CENTRO, width,height l'ingombro totale.
Area utile x=0.15..11.85, y=1.05..7.25; titolo sopra e conclusione sotto sono automatici.
Progetta liberamente la disposizione, con 3–7 elementi quando bastano. Esempio di coordinate ampie:
tre colonne x=2,6,10 con width=3; due righe y=2.6,5.5 con height=1.6.
Per grid/bars/plot riserva width>=4.5, height>=3.5 e poche annotazioni vicine.
Un diagramma di flusso usa circle per inizio/fine, decision per condizioni, document/database quando
semanticamente corretti e connections per le frecce: non rappresentare tutto con box.
Niente sovrapposizioni. Usa testo BREVE (2–5 parole), caption solo se chiarisce, non ripetere la prosa.
Le connections referenziano gli id degli elementi; label spiega la relazione, non 'collegamento'.
Le frecce vengono instradate evitando gli elementi. Lascia spazio tra gli elementi per le etichette.
stage determina l'ordine di rivelazione nell'animazione: prima dati/ingressi, poi trasformazione, infine risultato.
Una decisione deve avere uscite etichettate distinte. Una relazione causale va nella direzione corretta.
title e takeaway spiegano ciò che si deve vedere. Nessun codice, URL, file, comandi o espressioni da eseguire.
"""
