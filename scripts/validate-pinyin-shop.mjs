/** Product references and known lesson/audio provenance must stay in content/. */
export function validatePinyinShop(shop, illustrations) {
  const errors = [];
  if (
    shop.version !== 1 ||
    shop.basketLimit !== 6 ||
    !Number.isInteger(shop.recognitionTimeoutMs) ||
    shop.recognitionTimeoutMs < 1000 ||
    shop.recognitionTimeoutMs > 30000
  )
    errors.push('shop: invalid rules');
  const ids = new Set();
  const targets = new Set();
  if (!Array.isArray(shop.products) || !shop.products.length)
    return [...errors, 'shop: missing products'];
  for (const product of shop.products) {
    if (!/^[a-z][a-z-]+$/.test(product.id) || ids.has(product.id))
      errors.push('shop: invalid or duplicate product');
    ids.add(product.id);
    if (targets.has(product.targetId)) errors.push('shop: duplicate target');
    targets.add(product.targetId);
    const target = illustrations.items[product.targetId];
    if (!target?.audioRef || !target?.pinyin || target.pinyin !== target.pinyin.normalize('NFC'))
      errors.push(`shop: invalid target ${product.targetId}`);
    if (!product.name || !product.icon || !['coral', 'gold', 'mint'].includes(product.color))
      errors.push(`shop: invalid appearance ${product.id}`);
  }
  return errors;
}
