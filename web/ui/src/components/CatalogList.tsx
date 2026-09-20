import { categoryLabel, groupCatalog } from "../catalog.ts";
import type { CatalogItem } from "../types.ts";

type CatalogListProps = {
  items: readonly CatalogItem[];
  selectedIds: readonly string[];
  blackId?: string;
  whiteId?: string;
  onSelect: (specimenId: string) => void;
};

export function CatalogList({
  items,
  selectedIds,
  blackId,
  whiteId,
  onSelect,
}: CatalogListProps) {
  const groups = groupCatalog(items);
  return (
    <div className="catalog-groups">
      {groups.map((group) => (
        <section key={group.category} className="catalog-section">
          <h2 className="catalog-group">{group.label}</h2>
          <ul className="catalog-list">
            {group.items.map((item) => (
              <CatalogCard
                key={item.specimen_id}
                item={item}
                selected={selectedIds.includes(item.specimen_id)}
                assignedBlack={blackId === item.specimen_id}
                assignedWhite={whiteId === item.specimen_id}
                onSelect={onSelect}
              />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

type CatalogCardProps = {
  item: CatalogItem;
  selected: boolean;
  assignedBlack: boolean;
  assignedWhite: boolean;
  onSelect: (specimenId: string) => void;
};

function CatalogCard({
  item,
  selected,
  assignedBlack,
  assignedWhite,
  onSelect,
}: CatalogCardProps) {
  const nameId = `specimen-${item.specimen_id}-name`;
  const descId = `specimen-${item.specimen_id}-desc`;
  const className = selected ? "catalog-item is-selected" : "catalog-item";
  return (
    <li className={className}>
      <h3 id={nameId} className="catalog-name">
        {item.display_name}
      </h3>
      <p className="catalog-category">{categoryLabel(item.category)}</p>
      <p id={descId} className="catalog-description">
        {item.description}
      </p>
      {assignedBlack || assignedWhite ? (
        <p className="catalog-slots">
          {assignedBlack ? <span className="catalog-slot-chip">黒</span> : null}
          {assignedWhite ? <span className="catalog-slot-chip">白</span> : null}
        </p>
      ) : null}
      {selected ? (
        <span className="catalog-check" aria-hidden="true">
          ✓
        </span>
      ) : null}
      <button
        type="button"
        className="catalog-card-hit"
        aria-pressed={selected}
        aria-labelledby={nameId}
        aria-describedby={descId}
        onClick={() => onSelect(item.specimen_id)}
      >
        選ぶ
      </button>
    </li>
  );
}
