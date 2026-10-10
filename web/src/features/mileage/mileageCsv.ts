// CSV quoting alone does not prevent spreadsheet formula evaluation.
export function mileageCsvCell(value: string) {
  const text = /^[\s\uFEFF]*[=+@-]/.test(value) || /^[\t\r\n]/.test(value) ? "'" + value : value;
  return '"' + text.replaceAll('"', '""') + '"';
}
