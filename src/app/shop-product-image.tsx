import { shopRules, type ShopProduct } from '../domain/pinyin-shop';

/** One local atlas, 96 unique illustrated cells; no emoji substitutions or remote assets. */
export function ShopProductImage({ product }: { product: ShopProduct }) {
  const { columns, rows, src } = shopRules.image;
  return (
    <span className="shop-product-art">
      <img
        src={src}
        alt={product.name}
        draggable={false}
        style={{
          width: `${columns * 100}%`,
          height: `${rows * 100}%`,
          left: `${-(product.imageIndex % columns) * 100}%`,
          top: `${-Math.floor(product.imageIndex / columns) * 100}%`,
        }}
      />
    </span>
  );
}
