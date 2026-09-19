import type { CatalogItem } from "../types.ts";

type CatalogListProps = {
  items: readonly CatalogItem[];
};

export function CatalogList({ items }: CatalogListProps) {
  return (
    <ul className="catalog-list">
      {items.map((item) => (
        <li key={item.specimen_id} className="catalog-item">
          <h3 className="catalog-name">{item.display_name}</h3>
          <p className="catalog-description">{item.description}</p>
        </li>
      ))}
    </ul>
  );
}
