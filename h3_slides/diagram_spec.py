"""A bounded scene language compiled into real Manim objects, never Python eval."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Number = Annotated[float, Field(ge=-1e9, le=1e9, allow_inf_nan=False)]
Tone = Literal["accent", "blue", "amber", "red", "violet", "neutral"]


class Element(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,31}$")
    type: Literal["box", "decision", "circle", "database", "document", "text", "grid", "bars", "plot"]
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
        if self.type == "bars" and len(self.labels) != len(self.values):
            raise ValueError(f"Barre {self.id}: ogni valore richiede un'etichetta")
        if self.type not in ("grid", "bars", "plot") and not self.text.strip():
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
    elements = [Element(id=f"n{i}", type="box", x=x, y=y, width=3, height=1.1,
                        text=text, stage=i+1) for i, ((x, y), text) in enumerate(zip(positions, labels))]
    connections = [] if diagram["kind"] == "comparison" else [
        Connection(source=f"n{i}", target=f"n{(i+1)%n}") for i in range(n if diagram["kind"] == "cycle" else n-1)]
    return ManimSceneSpec(title="Diagramma", elements=elements, connections=connections)


SCENE_PROMPT = """PROGETTA UNA SCENA MANIM, non una slide di testo e non una lista di scatole.
Il disegno deve spiegare un meccanismo, una struttura o dati concreti presenti nella slide.
Non inventare misurazioni. Per esempi numerici inventati a scopo didattico scrivi 'Esempio illustrativo'.
Scegli il linguaggio visivo pertinente: decision per condizioni e rami sì/no; database per archivi;
document per file; circle per entità; grid per pixel/matrici (valori 0..1); bars per confronti quantitativi
(labels per ogni valore); plot per segnali/campioni; text per annotazioni. Non forzare grafici numerici su argomenti senza dati.
Tu progetti elementi e relazioni, Manim costruisce e renderizza la scena.
Canvas 12 × 8, x cresce verso destra e y verso il basso. x,y sono il CENTRO, width,height l'ingombro totale.
Area utile x=0.15..11.85, y=1.05..7.25; titolo sopra e conclusione sotto sono automatici.
Progetta liberamente la disposizione, con 3–7 elementi quando bastano. Esempio di coordinate ampie:
tre colonne x=2,6,10 con width=3; due righe y=2.6,5.5 con height=1.6.
Per grid/bars/plot riserva width>=4.5, height>=3.5 e poche annotazioni vicine.
Niente sovrapposizioni. Usa testo BREVE (2–5 parole), caption solo se chiarisce, non ripetere la prosa.
Le connections referenziano gli id degli elementi; label spiega la relazione, non 'collegamento'.
Le frecce vengono instradate evitando gli elementi. Lascia spazio tra gli elementi per le etichette.
stage determina l'ordine di rivelazione nell'animazione: prima dati/ingressi, poi trasformazione, infine risultato.
Una decisione deve avere uscite etichettate distinte. Una relazione causale va nella direzione corretta.
title e takeaway spiegano ciò che si deve vedere. Nessun codice, URL, file, comandi o espressioni da eseguire.
"""
