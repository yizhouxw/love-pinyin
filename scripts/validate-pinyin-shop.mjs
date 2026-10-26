/** Release contract: 8 x 12 illustrated goods, decorative integer prices, independent teaching deck. */
export function validatePinyinShop(shop, illustrations, readImage) {
  const errors = [];
  if (
    shop.version !== 2 ||
    !['mock', 'unavailable'].includes(shop.recognitionMode) ||
    shop.basketLimit !== 6 ||
    shop.recognitionTimeoutMs !== 5000 ||
    !Number.isInteger(shop.minimumAudioMs) ||
    shop.minimumAudioMs < 300 ||
    shop.minimumAudioMs > 1000 ||
    !Number.isInteger(shop.pollIntervalMs) ||
    shop.pollIntervalMs < 200 ||
    shop.pollIntervalMs > 1000
  )
    errors.push('shop: invalid timing or basket rules');
  if (
    !Array.isArray(shop.shelves) ||
    shop.shelves.length !== 8 ||
    new Set(shop.shelves.map((s) => s.id)).size !== 8 ||
    shop.shelves.some((s) => !s.name || !/^[a-z]+$/.test(s.id))
  )
    errors.push('shop: expected eight named unique shelves');
  if (!Array.isArray(shop.products) || shop.products.length !== 96)
    return [...errors, 'shop: expected 96 products'];
  const ids = new Set();
  const images = new Set();
  for (const product of shop.products) {
    if (!/^[a-z]+-[a-z]+$/.test(product.id) || ids.has(product.id))
      errors.push('shop: invalid or duplicate product');
    ids.add(product.id);
    if (!product.name || !shop.shelves.some((s) => s.id === product.shelfId))
      errors.push('shop: invalid product shelf/name');
    if (
      !Number.isInteger(product.priceCents) ||
      product.priceCents <= 0 ||
      product.priceCents > 99999
    )
      errors.push('shop: price must be bounded integer cents');
    if (
      !Number.isInteger(product.imageIndex) ||
      product.imageIndex < 0 ||
      product.imageIndex >= 96 ||
      images.has(product.imageIndex)
    )
      errors.push('shop: missing or duplicate product image');
    images.add(product.imageIndex);
    if ('targetId' in product || 'pinyin' in product)
      errors.push('shop: goods must not bind a reading target');
  }
  for (const shelf of shop.shelves)
    if (shop.products.filter((p) => p.shelfId === shelf.id).length !== 12)
      errors.push(`shop: ${shelf.id} needs 12 goods`);
  if (
    !Array.isArray(shop.targetIds) ||
    !shop.targetIds.length ||
    new Set(shop.targetIds).size !== shop.targetIds.length
  )
    errors.push('shop: invalid independent target deck');
  else
    for (const id of shop.targetIds) {
      const target = illustrations.items[id];
      if (!target?.audioRef || !target?.pinyin || target.pinyin !== target.pinyin.normalize('NFC'))
        errors.push(`shop: invalid target ${id}`);
    }
  if (
    !Array.isArray(shop.vowelTargetIds) ||
    shop.vowelTargetIds.some((id) => !shop.targetIds.includes(id))
  )
    errors.push('shop: invalid vowel task metadata');
  if (
    shop.image?.src !== '/shop/products-photo-atlas.png' ||
    shop.image.columns !== 12 ||
    shop.image.rows !== 8
  )
    errors.push('shop: invalid atlas geometry');
  else if (readImage) {
    try {
      const data = readImage(shop.image.src);
      if (
        data.length < 24 ||
        data.readUInt32BE(0) !== 0x89504e47 ||
        data.readUInt32BE(16) % 12 ||
        data.readUInt32BE(20) % 8 ||
        data.readUInt32BE(16) / 12 !== data.readUInt32BE(20) / 8 ||
        data.readUInt32BE(16) < 1536
      )
        errors.push('shop: invalid or undersized image atlas');
    } catch {
      errors.push('shop: image atlas unavailable');
    }
  }
  return errors;
}
