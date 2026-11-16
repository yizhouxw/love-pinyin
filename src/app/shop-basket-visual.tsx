import type { ShopProduct } from '../domain/pinyin-shop';
import { ShopProductImage } from './shop-product-image';

export function ShopBasketVisual({ products }: { products: readonly ShopProduct[] }) {
  return (
    <span className="shop-basket-visual" aria-hidden="true">
      <span className="shop-basket-handle" />
      <span className="shop-basket-goods">
        {products.map((product) => (
          <ShopProductImage key={product.id} product={product} />
        ))}
      </span>
      <span className="shop-basket-front" />
    </span>
  );
}
