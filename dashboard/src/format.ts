/** Display formatting shared by prose, charts, and tables. */

/** A ratio as a percentage with one decimal place: 0.3504 → "35.0%". */
export function percent(ratio: number): string {
  return `${(ratio * 100).toFixed(1)}%`;
}

/** An integer count with thousands separators: 817426 → "817,426". */
export function count(value: number): string {
  return value.toLocaleString("en-US");
}

/** A Gini coefficient with three decimals. */
export function gini(value: number): string {
  return value.toFixed(3);
}

/** A stored ratio at full stored precision, for detail tables. */
export function stored(value: number): string {
  return String(value);
}
