// ponytail: placeholder data for the dashboard redesign preview only.
// Delete this file and wire real endpoints once each module's backend piece lands — never ship to prod.

const NOMBRES = [
  'Cabo de Hornos', 'Estrella del Sur', 'Punta Arenas', 'Bahía Azul', 'Rayén',
  'Tehuelche', 'Costa Brava', 'Antares', 'Kawésqar', 'Aurora Austral',
  'Islote Negro', 'Pacífico Sur', 'Faro Diego', 'Chiloé Uno',
]

const RECURSOS = [
  'Extintor PQS 6kg', 'Balsa salvavidas', 'Chaleco salvavidas', 'Bengala roja',
  'Botiquín primeros auxilios', 'Radio VHF portátil', 'GPS de emergencia',
  'Manguera contra incendio', 'MEDIOS PARA ACCIONAR MÁQUINAS PRINCIPALES Y DE OTRA ÍNDOLE DESDE SALA DE CONTROL.', 'Aro salvavidas',
]

// Intentionally long/technical — this is real-world phrasing for inspection requirements.
const REQUISITOS = [
  'Presión de descarga dentro del rango operativo especificado por el fabricante',
  'Certificado de mantención vigente emitido por organismo acreditado',
  'Ausencia de corrosión visible en cuerpo del extintor y válvula de descarga',
  'Sello de seguridad intacto y sin evidencia de manipulación previa',
  'MEDIOS PARA ACCIONAR MÁQUINAS PRINCIPALES Y DE OTRA ÍNDOLE DESDE SALA DE CONTROL, PUENTE DE NAVEGACIÓN Y LOCALMENTE EN SALA DE MÁQUINAS',
  'Iluminación de emergencia funcional en ruta de escape principal y secundaria',
]

const OBSERVACIONES = [
  'Manómetro marca 8 bar, bajo el mínimo de 12 bar establecido en ficha técnica del fabricante para este modelo específico.',
  'Certificado venció el 14/03/2026 según registro de la última mantención realizada por proveedor externo autorizado.',
  'Se detectó picadura de corrosión de aproximadamente 3cm en la base del cuerpo, cerca de la soldadura del soporte.',
  'Sello roto, no es posible verificar si el equipo fue recargado o manipulado desde la última inspección registrada.',
  'Se solicitó a bodega el reemplazo inmediato, pieza no disponible en stock local, tiempo estimado de llegada 5 días.',
  'Prueba funcional arrojó tiempo de respuesta superior al máximo permitido por la normativa vigente para este tipo de sistema.',
]

const PERIODICIDADES = ['Mensual', 'Trimestral', 'Semestral', 'Anual']

const CREW = ['J. Soto', 'M. Pérez', 'R. Contreras', 'C. Vidal', 'F. Muñoz', 'A. Rojas', 'P. Herrera']

function seedRandom(seed) {
  let s = seed
  return () => {
    s = (s * 9301 + 49297) % 233280
    return s / 233280
  }
}

const rand = seedRandom(42)
const pick = (arr) => arr[Math.floor(rand() * arr.length)]
const int = (min, max) => Math.floor(rand() * (max - min + 1)) + min

export function buildFleet(count = 14) {
  return NOMBRES.slice(0, count).map((nombre, i) => {
    const fallosActivos = rand() < 0.35 ? int(1, 4) : 0
    const fallosNuevos = fallosActivos > 0 && rand() < 0.5 ? int(1, fallosActivos) : 0
    const fichasHoy = rand() < 0.5 ? int(1, 6) : 0
    const completitud = int(35, 100)
    const vencidos = Math.max(0, Math.round((100 - completitud) / 18) + int(-1, 1))
    const horasAtras = int(1, 96)
    return {
      id: i + 1,
      nombre,
      matricula: `${pick(['VP', 'CB', 'SN', 'TQ'])}-${int(1000, 9999)}`,
      fallosActivos,
      fallosNuevos,
      fichasHoy,
      completitud,
      vencidos,
      ultimoRegistro: horasAtras < 24 ? `hace ${horasAtras} h` : `hace ${Math.round(horasAtras / 24)} d`,
    }
  })
}

// Feed only surfaces events within this window — the count badge is only meaningful next to it.
export const FEED_WINDOW_DAYS = 3

export function buildFeedEvents(fleet, count = 13) {
  const now = Date.now()
  const windowMinutes = FEED_WINDOW_DAYS * 24 * 60
  return Array.from({ length: count }, (_, i) => {
    const tipo = rand() > 0.4 ? 'nuevo' : 'resuelto'
    // an item fails when 1+ of its requisitos fail; each failed requisito carries its own observación
    const requisitosFallidos = tipo === 'nuevo'
      ? Array.from({ length: rand() < 0.4 ? int(2, 3) : 1 }, () => ({
          requisito: pick(REQUISITOS),
          observacion: pick(OBSERVACIONES),
        }))
      : []
    return {
      id: i + 1,
      tipo,
      nave: pick(fleet).nombre,
      item: pick(RECURSOS),
      usuario: pick(CREW),
      requisitosFallidos,
      timestamp: now - int(4, windowMinutes) * 60 * 1000,
    }
  }).sort((a, b) => b.timestamp - a.timestamp)
}

export function buildVencimientos(fleet, count = 11) {
  const now = Date.now()
  const day = 86400000
  return Array.from({ length: count }, (_, i) => ({
    id: i + 1,
    nave: pick(fleet).nombre,
    periodicidad: pick(PERIODICIDADES),
    avance: int(20, 95),
    fecha: now + int(-9, 14) * day,
  })).sort((a, b) => a.fecha - b.fecha)
}

// Calendar-aligned (Monday-start) window so week columns line up with real dates.
export function buildActivity(fleet, weeks = 8) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const daysFromMonday = (today.getDay() + 6) % 7
  const thisMonday = new Date(today)
  thisMonday.setDate(today.getDate() - daysFromMonday)
  const start = new Date(thisMonday)
  start.setDate(thisMonday.getDate() - (weeks - 1) * 7)
  const totalDays = weeks * 7

  return fleet.map((nave) => ({
    id: nave.id,
    nombre: nave.nombre,
    matricula: nave.matricula,
    days: Array.from({ length: totalDays }, (_, i) => {
      const date = new Date(start)
      date.setDate(start.getDate() + i)
      const isFuture = date > today
      const dow = date.getDay()
      const weekendDampener = (dow === 0 || dow === 6) ? 0.4 : 1
      const count = isFuture ? 0 : (rand() < 0.35 ? 0 : Math.round(int(1, 6) * weekendDampener))
      return { date: date.getTime(), count }
    }),
  }))
}
