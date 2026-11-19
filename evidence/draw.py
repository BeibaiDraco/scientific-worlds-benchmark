"""Draw the recorded component and its drive relations for the article and README."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
case = json.loads((HERE / "discovery.json").read_bytes())
score = json.loads((HERE / "scorecard.json").read_bytes())["conditions"]["M"]
ink, blue, faint, ground = "#102e43", "#174c6d", "#b6c7cd", "#edf1f2"


def text(x, y, s, size, fill=ink, anchor="start", serif=False):
    font = "Georgia,serif" if serif else "Menlo,monospace"
    return f'<text x="{x}" y="{y}" fill="{fill}" text-anchor="{anchor}" font-family="{font}" font-size="{size}">{s}</text>'


def wire_grid(x, y, dx, dy, fontsize):
    parts = []
    positions = {port: (x+col*dx, y+row*dy) for row,line in enumerate(case["grid"])
                 for col,port in enumerate(line)}
    for dest, source, invert in case["wires"]:
        sx,sy = positions[source]
        tx,ty = positions[dest]
        bend = dx * .37
        dash = ' stroke-dasharray="4 4"' if invert else ''
        parts.append(f'<path d="M {sx+8} {sy} C {sx+bend} {sy}, {tx+bend} {ty}, {tx+8} {ty}" fill="none" stroke="{blue}" stroke-width="2"{dash}/>')
        parts.append(f'<path d="m {tx+12} {ty-3} -5 3 5 3" fill="none" stroke="{blue}" stroke-width="1.7"/>')
    active={p for d,s,i in case["wires"] for p in (d,s)}
    for p,(cx,cy) in positions.items():
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="3.6" fill="{blue if p in active else faint}"/>')
        parts.append(text(cx-7,cy+4,str(p),fontsize,blue if p in active else "#526b77","end"))
    return ''.join(parts)


def svg(width, height, title, parts):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">'
            f'<title>{title}</title><rect width="100%" height="100%" fill="{ground}"/>' + ''.join(parts) + '</svg>\n')


def render():
    figure = [
        text(24,31,"32 INPUTS  /  RECOVERED ARRANGEMENT",14),
        wire_grid(76,77,84,49,14),
        text(24,269,"Solid: copy the source bit.   Dashed: invert it.",14),
    ]
    (HERE / "component.svg").write_text(svg(740,292,"The eight wiring rules from the 32-port discovery",figure))
    card = [
        text(69,69,"THE MEASURE OF WORLDS    /    v1.0",22,blue),
        text(67,164,"Virtual Brain",80,serif=True),
        text(69,233,"How does an AI scientist decide what to study?",36,serif=True),
        '<path d="M69 276 H1131" stroke="#809aa7"/>',
        text(63,450,f'{score["successes"]}/{score["sessions"]}',120,blue,serif=True),
        text(71,498,f'ASTRA 6.0 MAX  ·  M  ·  {score["percent"]:g}%',21),
        text(71,542,"Microscopic law supplied",21),
        text(71,573,"10–12 active hours per session",18),
        wire_grid(560,331,74,53,14),
        text(521,561,"32 inputs. Eight wiring rules.",20,blue),
        text(521,590,"Used in all eight working devices.",19,blue)
    ]
    (HERE / "cover.svg").write_text(svg(1200,630,"The Measure of Worlds v1.0 · Virtual Brain — Astra 6.0 Max delivered in two of 25 M attempts",card))


if __name__ == "__main__":
    render()
