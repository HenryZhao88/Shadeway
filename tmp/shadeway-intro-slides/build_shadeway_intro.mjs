import fs from 'node:fs/promises';
import { Presentation, PresentationFile } from '@oai/artifact-tool';

const OUT = '/Users/tahmid/Documents/Code/Shadeway/Shadeway_Intro_Slides.pptx';
const HERE = '/Users/tahmid/Documents/Code/Shadeway/tmp/shadeway-intro-slides';
const HERO = `${HERE}/shadeway-hero.png`;

const C = {
  ink: '#0D1720',
  navy: '#101A25',
  deep: '#0A1017',
  slate: '#465460',
  mist: '#DDE6E8',
  paper: '#F6F5F0',
  saffron: '#F1B54A',
  orange: '#E66F3C',
  teal: '#1E9B8F',
  sky: '#76C8E4',
  green: '#74A854',
  line: '#B9C7C9',
};

function addText(slide, text, left, top, width, height, style = {}, name) {
  const box = slide.shapes.add({
    geometry: 'textbox',
    name,
    position: { left, top, width, height },
    fill: 'none',
    line: { style: 'solid', fill: 'none', width: 0 },
  });
  box.text = text;
  box.text.style = {
    fontFace: style.fontFace ?? 'Aptos',
    fontSize: style.fontSize ?? 20,
    color: style.color ?? C.ink,
    bold: style.bold ?? false,
    italic: style.italic ?? false,
    alignment: style.alignment ?? 'left',
    ...style,
  };
  return box;
}

function rect(slide, left, top, width, height, fill, options = {}) {
  return slide.shapes.add({
    geometry: options.geometry ?? 'rect',
    name: options.name,
    position: { left, top, width, height },
    fill,
    line: options.line ?? { style: 'solid', fill: 'none', width: 0 },
    borderRadius: options.borderRadius,
    shadow: options.shadow,
  });
}

function dot(slide, x, y, color, size = 10) {
  return slide.shapes.add({
    geometry: 'ellipse',
    position: { left: x, top: y, width: size, height: size },
    fill: color,
    line: { style: 'solid', fill: 'none', width: 0 },
  });
}

async function writeBlob(path, blob) {
  await fs.writeFile(path, new Uint8Array(await blob.arrayBuffer()));
}

async function main() {
  const deck = Presentation.create({ slideSize: { width: 1280, height: 720 } });
  const heroBytes = await fs.readFile(HERO);

  // Slide 1: problem and human stakes.
  const s1 = deck.slides.add();
  s1.background.fill = C.deep;
  s1.images.add({
    blob: heroBytes,
    contentType: 'image/png',
    alt: 'Midtown sidewalk divided between strong sun and building shade',
    fit: 'cover',
    position: { left: 520, top: 0, width: 760, height: 720 },
  });
  rect(s1, 485, 0, 795, 720, '#080D13/40');
  rect(s1, 0, 0, 592, 720, C.deep);
  rect(s1, 525, 0, 180, 720, '#0A1017/50');
  rect(s1, 64, 67, 56, 4, C.saffron);
  addText(s1, 'SHADEWAY  |  HEAT-AWARE WALKING', 64, 87, 430, 28, {
    fontSize: 14, bold: true, color: C.sky, characterSpacing: 1,
  }, 's1-kicker');
  addText(s1, 'A fast route is not always\nthe easiest walk.', 64, 136, 500, 164, {
    fontFace: 'Aptos Display', fontSize: 53, bold: true, color: '#F7F8F6',
  }, 's1-title');
  addText(s1, 'Direct sun can turn a short city walk into the hardest part of someone’s day. Most maps only optimize for minutes.', 64, 326, 445, 92, {
    fontSize: 22, color: '#C9D5D7',
  }, 's1-subtitle');
  rect(s1, 64, 462, 430, 1, '#43525C');
  addText(s1, 'WHAT PEOPLE ACTUALLY NEED', 64, 486, 390, 22, {
    fontSize: 13, bold: true, color: C.sky, characterSpacing: 1,
  }, 's1-need-label');
  addText(s1, 'Which route feels better?\nWhich side stays cooler?\nShould I leave later?', 64, 521, 410, 110, {
    fontSize: 22, bold: true, color: '#F7F8F6',
  }, 's1-need-copy');
  addText(s1, '01', 64, 657, 60, 22, { fontSize: 14, color: '#80929A' }, 's1-page');
  addText(s1, 'Heat changes the route', 104, 657, 250, 22, { fontSize: 14, color: '#80929A' }, 's1-footer');
  // Editorial caption over image.
  rect(s1, 940, 568, 260, 80, '#101A25/84', { borderRadius: 12 });
  addText(s1, 'Same city.\nA different walk.', 964, 585, 205, 50, {
    fontSize: 19, bold: true, color: '#F7F8F6',
  }, 's1-image-caption');
  s1.speakerNotes.textFrame.setText(`[Sources]\n- Hero image: generated with OpenAI image generation on 2026-08-30.\n- Hackathon framing: https://hacksocial2026.devpost.com/ (read 2026-08-30).`);
  s1.speakerNotes.setVisible(true);

  // Slide 2: concise product proposition with an editable, illustrative product composition.
  const s2 = deck.slides.add();
  s2.background.fill = C.paper;
  rect(s2, 64, 62, 56, 4, C.teal);
  addText(s2, 'SHADEWAY  |  WHAT WE BUILT', 64, 82, 400, 25, {
    fontSize: 14, bold: true, color: C.teal, characterSpacing: 1,
  }, 's2-kicker');
  addText(s2, 'A walking planner\nfor how the walk feels.', 64, 128, 530, 143, {
    fontFace: 'Aptos Display', fontSize: 48, bold: true, color: C.ink,
  }, 's2-title');
  addText(s2, 'Shadeway turns invisible heat exposure into practical choices before you leave.', 64, 290, 470, 61, {
    fontSize: 22, color: C.slate,
  }, 's2-subtitle');

  // Three concise benefits, arranged as an editorial rail rather than a card grid.
  const benefitY = [397, 468, 539];
  const nums = ['01', '02', '03'];
  const heads = ['Cooler route choices', 'The sun moves with you', 'Practical guidance'];
  const bodies = [
    'Compare the fastest walk with options that feel cooler.',
    'Each block is checked when the walker actually reaches it.',
    'Choose a side of the street, a better time, or a place to cool off.',
  ];
  for (let i = 0; i < 3; i++) {
    addText(s2, nums[i], 64, benefitY[i], 52, 22, { fontSize: 14, bold: true, color: C.orange }, `s2-num-${i}`);
    addText(s2, heads[i], 118, benefitY[i] - 3, 270, 26, { fontSize: 20, bold: true, color: C.ink }, `s2-head-${i}`);
    addText(s2, bodies[i], 118, benefitY[i] + 24, 350, 46, { fontSize: 16, color: C.slate }, `s2-body-${i}`);
  }
  addText(s2, '02', 64, 657, 60, 22, { fontSize: 14, color: '#87969B' }, 's2-page');
  addText(s2, 'A route people can act on', 104, 657, 310, 22, { fontSize: 14, color: '#87969B' }, 's2-footer');

  // Product visualization, intentionally labeled illustrative so it is not presented as live weather.
  rect(s2, 625, 62, 591, 594, '#FFFFFF', { borderRadius: 24, line: { style: 'solid', fill: '#D7E0DF', width: 1 }, shadow: 'shadow-md', name: 's2-product-frame' });
  rect(s2, 625, 62, 591, 52, C.navy, { borderRadius: 24, name: 's2-product-header' });
  rect(s2, 625, 88, 591, 26, C.navy);
  addText(s2, 'shadeway', 653, 77, 160, 22, { fontFace: 'Aptos Display', fontSize: 20, bold: true, color: '#F7F8F6' }, 's2-product-brand');
  dot(s2, 1142, 80, C.orange, 10);
  dot(s2, 1162, 80, C.saffron, 10);
  dot(s2, 1182, 80, C.teal, 10);
  addText(s2, 'PENN STATION  →  ROCKEFELLER CENTER', 653, 135, 470, 18, {
    fontSize: 12, bold: true, color: '#718087', characterSpacing: 1,
  }, 's2-route-label');
  addText(s2, 'One extra minute.\nA meaningfully cooler walk.', 653, 163, 420, 70, {
    fontFace: 'Aptos Display', fontSize: 29, bold: true, color: C.ink,
  }, 's2-route-title');

  // Route map structure and thermal path, using compact native shapes as an explanatory diagram.
  rect(s2, 653, 264, 307, 113, '#EEF3F1', { borderRadius: 14 });
  const mapLines = [
    [674, 282, 252, 2], [674, 305, 252, 2], [674, 328, 252, 2], [674, 351, 252, 2],
  ];
  for (const [x, y, w, h] of mapLines) rect(s2, x, y, w, h, '#CAD7D5');
  const verticals = [700, 745, 790, 835, 880];
  for (const x of verticals) rect(s2, x, 275, 2, 90, '#CAD7D5');
  rect(s2, 690, 344, 61, 6, C.orange, { borderRadius: 6 });
  rect(s2, 746, 321, 48, 6, C.saffron, { borderRadius: 6 });
  rect(s2, 788, 297, 60, 6, C.teal, { borderRadius: 6 });
  rect(s2, 843, 275, 69, 6, C.teal, { borderRadius: 6 });
  dot(s2, 681, 340, C.orange, 15);
  dot(s2, 906, 268, C.teal, 15);
  addText(s2, 'start', 665, 356, 45, 14, { fontSize: 11, color: C.slate }, 's2-map-start');
  addText(s2, 'finish', 891, 285, 46, 14, { fontSize: 11, color: C.slate }, 's2-map-finish');

  // Right-side difference block.
  rect(s2, 982, 264, 196, 113, '#0F1A23', { borderRadius: 14 });
  addText(s2, 'FEELS LIKE', 1002, 282, 130, 16, { fontSize: 11, bold: true, color: C.sky, characterSpacing: 1 }, 's2-feels-label');
  addText(s2, 'fastest  41°', 1002, 304, 150, 23, { fontSize: 18, color: '#BFC8C9' }, 's2-fastest');
  addText(s2, 'shadeway  33°', 1002, 331, 160, 28, { fontSize: 20, bold: true, color: '#F7F8F6' }, 's2-shadeway');

  addText(s2, 'WHEN TO LEAVE', 653, 410, 145, 18, { fontSize: 12, bold: true, color: C.teal, characterSpacing: 1 }, 's2-chart-label');
  addText(s2, 'A later departure can feel cooler, even before sunset.', 653, 433, 430, 23, { fontSize: 16, color: C.slate }, 's2-chart-caption');
  s2.charts.add('line', {
    position: { left: 650, top: 466, width: 503, height: 126 },
    categories: ['3 PM', '4 PM', '5 PM', '6 PM'],
    series: [{
      name: 'Feels like', values: [39, 36, 33, 29],
      line: { style: 'solid', fill: C.orange, width: 3 },
      marker: { symbol: 'circle', size: 6 },
    }],
    hasLegend: false,
    chartFill: '#FFFFFF',
    plotAreaFill: '#FFFFFF',
    chartLine: { style: 'solid', fill: 'none', width: 0 },
    plotAreaLine: { style: 'solid', fill: 'none', width: 0 },
    xAxis: { textStyle: { fill: C.slate, fontSize: 11 }, line: { style: 'solid', fill: '#D7E0DF', width: 1 }, majorGridlines: null },
    yAxis: { visible: false, min: 25, max: 42, majorGridlines: { style: 'solid', fill: '#E3EAE8', width: 1 } },
  });
  addText(s2, 'Illustrative product view. Route conditions update with time and local weather.', 653, 612, 500, 16, { fontSize: 11, color: '#87969B', italic: true }, 's2-disclaimer');
  s2.speakerNotes.textFrame.setText(`[Sources]\n- Product capabilities: Shadeway repository README.md and web/src/ui components, reviewed 2026-08-30.\n- Illustrative route values are a product-story visualization, not a claim about a live route at a particular time.\n- Hackathon framing: https://hacksocial2026.devpost.com/ (read 2026-08-30).`);
  s2.speakerNotes.setVisible(true);

  for (let index = 0; index < deck.slides.items.length; index++) {
    const slide = deck.slides.items[index];
    await writeBlob(`${HERE}/slide-${index + 1}.png`, await deck.export({ slide, format: 'png', scale: 2 }));
    await fs.writeFile(`${HERE}/slide-${index + 1}.layout.json`, await (await slide.export({ format: 'layout' })).text());
  }
  const pptx = await PresentationFile.exportPptx(deck);
  await pptx.save(OUT);
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
