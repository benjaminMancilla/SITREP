// Parsea un string "YYYY-MM-DD" (sin hora) como medianoche en la zona horaria
// local del navegador. new Date(str) lo interpretaría como medianoche UTC,
// lo que corre la fecha un día hacia atrás en timezones negativos (ej. Chile).
export function localDateMs(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number)
  return new Date(y, m - 1, d).getTime()
}
