import './browser-env.mjs';
import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import {chromium} from 'playwright-chromium';
import {slideHTML, slideCSS, fitSlide} from '../static/deck.mjs';

// Synthetic fixtures only. This suite measures the shared DOM renderer and never
// exports a document, captures a screenshot, contacts an API, or reads project data.
const paragraphs = {
  3: 'Un sistema collega osservazioni, modelli e decisioni attraverso passaggi verificabili. Ogni parte conserva il proprio ruolo e contribuisce a spiegare il risultato. Confrontare casi diversi aiuta a riconoscere relazioni, limiti e condizioni del processo.',
  4: 'Osservare un processo significa distinguere dati, passaggi e risultati. Un esempio concreto permette di confrontare le parti e spiegare come cambiano le loro relazioni nel tempo.',
};
const source = 'Documento dimostrativo, sezione 12, p. 24';
const heading = 'Analisi multidisciplinare dei processi';
const svg = (width, height, color) => 'data:image/svg+xml,' + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="' + width + '" height="' + height +
  '"><rect width="100%" height="100%" fill="' + color + '"/></svg>');
const urls = {diagram: svg(640, 360, '#c6d9ed'), image: svg(480, 320, '#d8e8d2')};
const project = {
  id: 'synthetic-density', title: 'Verifica della composizione', theme: 'ink',
  font: 'Arial', template: 'auto', text_density: 'complete',
  use_manim_diagrams: true, use_source_images: true, visual_assets: [],
  sources: [{id: 'synthetic-source', images: [{id: 'synthetic-photo.png', label: 'Immagine sintetica'}]}],
};
const makeSlide = count => ({
  id: 'density-' + count, status: 'ready', revision: 1,
  diagram_render: {engine: 'manim', asset: 'synthetic-diagram.png'},
  content: {
    title: 'Relazioni e risultati di un sistema', subtitle: 'Osservazioni, passaggi e confronto dei casi.',
    layout: 'visual-right', layout_locked: false, bullets: [], sources: [], notes: '',
    image_id: 'synthetic-photo.png', image_origin: 'source', image_placeholder: false,
    diagram: {kind: 'manim', brief: 'Relazioni tra elementi sintetici', scene: {}},
    blocks: Array.from({length: count}, (_, index) => ({
      kind: index % 2 ? 'example' : 'explanation', heading: heading + ' ' + (index + 1),
      text: paragraphs[count], source,
    })),
  },
});

let browser;
before(async () => { browser = await chromium.launch({headless: true}); });
after(async () => { await browser?.close(); });

async function render(slide, scale) {
  const page = await browser.newPage({viewport: {width: 1400, height: 900}});
  // Every resource is inline; an unexpected external request is a test failure.
  const requests = [], errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => {
    requests.push(route.request().url());
    return route.abort();
  });
  await page.setContent('<!doctype html><meta charset="utf-8"><style>' + slideCSS +
    'body{margin:0}.slide-frame{transform:scale(' + scale + ');transform-origin:top left}</style>' +
    slideHTML(project, slide, 0, urls));
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all([...document.images].map(image => image.decode()));
  });
  return {page, frame: page.locator('.slide-frame'), requests, errors};
}

// All coordinates are converted back to the 1280x720 slide space, so the same
// strict checks apply to full-size output and a scaled editor preview.
function inspect(frame) {
  const root = frame.getBoundingClientRect(), scale = root.width / 1280;
  const rect = element => {
    const r = element.getBoundingClientRect();
    return {x: (r.left - root.left) / scale, y: (r.top - root.top) / scale,
      w: r.width / scale, h: r.height / scale};
  };
  const within = (inner, outer) => inner.x >= outer.x - 1 && inner.y >= outer.y - 1 &&
    inner.x + inner.w <= outer.x + outer.w + 1 && inner.y + inner.h <= outer.y + outer.h + 1;
  const overlaps = (a, b) => Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x) > 1 &&
    Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y) > 1;
  const issues = [], canvas = {x: 0, y: 0, w: 1280, h: 720};
  const boxes = [...frame.querySelectorAll('.prose-box')];
  for (const [index, box] of boxes.entries()) {
    const bounds = rect(box), children = [...box.querySelectorAll('h2,p,.prose-source')];
    if (!within(bounds, canvas)) issues.push('block ' + index + ': box leaves the slide');
    for (const child of children) {
      const label = 'block ' + index + ' ' + child.dataset.editField;
      if (!within(rect(child), bounds)) issues.push(label + ': element leaves its box');
      if (child.scrollWidth > child.clientWidth + 2 || child.scrollHeight > child.clientHeight + 2)
        issues.push(label + ': text overflows its element');
      const range = document.createRange();
      range.selectNodeContents(child);
      for (const r of range.getClientRects()) {
        const text = {x: (r.left - root.left) / scale, y: (r.top - root.top) / scale,
          w: r.width / scale, h: r.height / scale};
        if (text.w > 0 && text.h > 0 && !within(text, bounds)) {
          issues.push(label + ': a text line leaves its box');
          break;
        }
      }
      const size = parseFloat(getComputedStyle(child).fontSize);
      if (child.matches('p') && size < 20) issues.push(label + ': body font below 20px');
      if (child.matches('.prose-source') && size < 12) issues.push(label + ': source font below 12px');
    }
    for (let a = 0; a < children.length; a++) for (let b = a + 1; b < children.length; b++)
      if (overlaps(rect(children[a]), rect(children[b])))
        issues.push('block ' + index + ': ' + children[a].dataset.editField + ' overlaps ' + children[b].dataset.editField);
  }
  const objects = [...frame.querySelectorAll('.heading,.prose-box,.visual,.footer')];
  for (let a = 0; a < objects.length; a++) for (let b = a + 1; b < objects.length; b++)
    if (overlaps(rect(objects[a]), rect(objects[b])))
      issues.push('separate slide objects overlap: ' + objects[a].className + ' / ' + objects[b].className);
  const media = [...frame.querySelectorAll('.visual')].map(element => ({
    kind: element.dataset.visualKind, key: element.dataset.freeKey, box: rect(element),
    src: element.matches('img') ? element.getAttribute('src') : element.querySelector('img')?.getAttribute('src'),
  }));
  for (const medium of media) {
    if (!within(medium.box, canvas)) issues.push(medium.kind + ': media leaves the slide');
    if (medium.box.w <= 0 || medium.box.h <= 0) issues.push(medium.kind + ': media is not visible');
  }
  return {
    issues, media, font: getComputedStyle(frame).fontFamily,
    text: boxes.map(box => ({heading: box.querySelector('h2').textContent,
      text: box.querySelector('p').textContent, source: box.querySelector('.prose-source').textContent})),
    placements: Object.fromEntries([...frame.querySelectorAll('[data-free-key]')].map(element => [
      element.dataset.freeKey, {box: rect(element), style: element.getAttribute('style')},
    ])),
  };
}

function checkContent(measured, slide, original) {
  assert.equal(JSON.stringify(slide), original, 'Rendering must not mutate the input');
  assert.deepEqual(measured.text, slide.content.blocks.map(({heading, text, source}) => ({heading, text, source})),
    'Fitting must preserve all headings, paragraphs and source text');
  assert.match(measured.font, /Arial/);
  assert.deepEqual(measured.media.map(({kind, key, src}) => ({kind, key, src})), [
    {kind: 'diagram', key: 'visual', src: urls.diagram},
    {kind: 'image', key: 'image', src: urls.image},
  ], 'Diagram and photograph remain separate media with independent slots and URLs');
}

for (const count of [3, 4]) for (const scale of [1, .43]) {
  test('dual media: ' + count + ' dense boxes fit at scale ' + scale, async () => {
    assert.equal('multidisciplinare'.length, 17);
    assert.ok(Math.abs(paragraphs[count].length - (count === 3 ? 250 : 175)) < 10);
    assert.ok(Math.abs(source.length - 40) < 5);
    const slide = makeSlide(count), original = JSON.stringify(slide);
    const {page, frame, requests, errors} = await render(slide, scale);
    try {
      const beforeText = await frame.textContent();
      const fitted = await frame.evaluate(fitSlide), measured = await frame.evaluate(inspect);
      checkContent(measured, slide, original);
      assert.equal(await frame.textContent(), beforeText, 'fitSlide must not truncate any text');
      assert.deepEqual(requests, [], 'No network requests are allowed');
      assert.deepEqual(errors, []);
      assert.deepEqual({overflow: fitted.overflow, issues: measured.issues}, {overflow: false, issues: []},
        'The chosen layout ' + fitted.layout + ' must contain readable, non-overlapping text and both media');
    } finally { await page.close(); }
  });
}

for (const scale of [1, .43]) {
  test('locked freeform preserves explicit dual-media geometry at scale ' + scale, async () => {
    const slide = makeSlide(3);
    // A feasible hand-placed composition isolates geometry locking from density.
    slide.content.blocks = slide.content.blocks.slice(0, 2).map(block => ({...block,
      heading: 'Relazioni del sistema', text: 'Dati e passaggi distinti aiutano a spiegare il risultato.'}));
    Object.assign(slide.content, {layout: 'freeform', layout_locked: true, freeform_base: 'editorial',
      freeform: {heading: {x: 48, y: 60, w: 1184, h: 120},
        'block-0': {x: 48, y: 200, w: 630, h: 205}, 'block-1': {x: 48, y: 425, w: 630, h: 225},
        visual: {x: 708, y: 200, w: 524, h: 240}, image: {x: 708, y: 460, w: 524, h: 190}}});
    const original = JSON.stringify(slide);
    const {page, frame, requests, errors} = await render(slide, scale);
    try {
      const before = await frame.evaluate(inspect), fitted = await frame.evaluate(fitSlide);
      const measured = await frame.evaluate(inspect);
      checkContent(measured, slide, original);
      assert.equal(fitted.layout, 'freeform');
      assert.deepEqual(measured.placements, before.placements, 'fitSlide must not move or resize locked elements');
      for (const [key, expected] of Object.entries(slide.content.freeform))
        for (const coordinate of ['x', 'y', 'w', 'h'])
          assert.ok(Math.abs(measured.placements[key].box[coordinate] - expected[coordinate]) < .1,
            key + ': locked ' + coordinate + ' must match the persisted rectangle');
      assert.deepEqual(requests, []);
      assert.deepEqual(errors, []);
      assert.deepEqual({overflow: fitted.overflow, issues: measured.issues}, {overflow: false, issues: []});
    } finally { await page.close(); }
  });
}
