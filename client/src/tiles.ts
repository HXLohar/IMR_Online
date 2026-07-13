// Canonical sort order matches server ALL_TILES: characters → dots → bamboo → winds → dragons
export const SORT_KEY: Record<string, number> = (() => {
  const keys: Record<string, number> = {}
  let i = 0
  for (let v = 1; v <= 9; v++) keys[`${v}c`] = i++
  for (let v = 1; v <= 9; v++) keys[`${v}d`] = i++
  for (let v = 1; v <= 9; v++) keys[`${v}b`] = i++
  for (const w of ['E', 'S', 'W', 'N']) keys[w] = i++
  for (const d of ['Wh', 'G', 'R']) keys[d] = i++
  return keys
})()

export function sortTiles(tiles: string[]): string[] {
  return [...tiles].sort((a, b) => (SORT_KEY[a] ?? 99) - (SORT_KEY[b] ?? 99))
}
