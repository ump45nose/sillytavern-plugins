/** Pages contain indices into native HTML blocks; no text or embedded nodes are copied. */
export function dialoguePages(blocks: { length: number; atomic?: boolean }[], capacity: number) {
  const pages: number[][] = [];
  let page: number[] = [], used = 0;
  const flush = () => { if (page.length) pages.push(page); page = []; used = 0; };
  blocks.forEach((block, index) => {
    if (block.atomic) { flush(); pages.push([index]); return; }
    if (used + block.length > capacity && page.length) flush();
    page.push(index); used += Math.max(1, block.length);
  });
  flush();
  return pages.length ? pages : [[]];
}

export function boundedPreference(value: number | undefined, fallback: number, min: number, max: number) {
  return Number.isFinite(value) ? Math.min(max, Math.max(min, value!)) : fallback;
}
