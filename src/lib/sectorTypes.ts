/**
 * Tipos para el panel dinámico por sector (SPEC-007 Comercial completo,
 * SPEC-008 Servicios/Manufactura de referencia + analítica multisectorial).
 * Datos siempre desde fixtures locales (src/mocks/sales.json,
 * services.json, manufacturing.json) — cero llamadas externas.
 */

/* ---------- SPEC-007 — Comercial / E-Commerce ---------- */

export type EtapaId =
  "prospecto" | "calificado" | "propuesta" | "negociacion" | "ganado" | "perdido";

export interface EtapaEmbudo {
  id: EtapaId;
  label: string;
  color: "muted" | "cyan" | "warning" | "indigo" | "success" | "danger";
}

export interface Oportunidad {
  id: string;
  cliente: string;
  monto: number;
  probabilidad: number;
  etapaId: EtapaId;
  canal: string;
  responsable: string;
  actualizadoAt: string;
}

export type EstadoPedido =
  | "pendiente_pago"
  | "confirmado"
  | "procesando"
  | "en_transito"
  | "entregado"
  | "cancelado";

export interface Pedido {
  id: string;
  cliente: string;
  importe: number;
  fecha: string;
  canal: string;
  estado: EstadoPedido;
}

export interface VentaCruzada {
  id: string;
  cliente: string;
  sugerencia: string;
  motivo: string;
  impactoEstimado: number;
}

export interface KpiComercial {
  id: string;
  label: string;
  value: number;
  delta: number;
  trend: "up" | "down" | "flat";
  format: "currency" | "percent" | "number";
}

export interface VentaMensual {
  mes: string;
  ventas: number;
  meta: number;
}

export interface SalesData {
  notaFicticia: string;
  etapas: EtapaEmbudo[];
  oportunidades: Oportunidad[];
  pedidos: Pedido[];
  ventaCruzada: VentaCruzada[];
  kpis: KpiComercial[];
  ventasPorMes: VentaMensual[];
}

/* ---------- SPEC-008 — Servicios / Consultoría (referencia) ---------- */

export interface HitoProyecto {
  id: string;
  proyecto: string;
  nombre: string;
  avance: number;
  estado: "completado" | "en_curso" | "en_riesgo";
  fechaLimite: string;
}

export interface HoraFacturable {
  id: string;
  consultor: string;
  proyecto: string;
  horas: number;
  tarifaHora: number;
  semana: string;
}

export interface IndicadorSla {
  id: string;
  cliente: string;
  indicador: string;
  estado: "cumplido" | "en_riesgo" | "incumplido";
  objetivo: string;
  actual: string;
}

export interface ReservaServicio {
  id: string;
  cliente: string;
  servicio: string;
  fecha: string;
  consultor: string;
  estado: "confirmada" | "pendiente" | "cancelada";
}

export interface ServicesData {
  notaFicticia: string;
  hitos: HitoProyecto[];
  horasFacturables: HoraFacturable[];
  sla: IndicadorSla[];
  reservas: ReservaServicio[];
}

/* ---------- SPEC-008 — Manufactura (referencia) ---------- */

export interface OrdenTrabajo {
  id: string;
  producto: string;
  cantidad: number;
  estado: "planificada" | "en_produccion" | "control_calidad" | "completada" | "detenida";
  avance: number;
  fechaEntrega: string;
}

export interface AlertaInventario {
  id: string;
  insumo: string;
  nivel: "normal" | "bajo" | "critico";
  stockActual: number;
  stockMinimo: number;
  unidad: string;
}

export interface ModuloSyncErp {
  id: string;
  nombre: string;
  estado: "sincronizado" | "con_advertencias" | "pendiente" | "error";
  registros: number;
  ultimaActualizacion: string;
}

export interface SyncErpEstado {
  ultimaSincronizacion: string;
  estadoGeneral: "sincronizado" | "con_advertencias" | "pendiente" | "error";
  modulos: ModuloSyncErp[];
}

export interface ManufacturingData {
  notaFicticia: string;
  ordenesTrabajo: OrdenTrabajo[];
  alertasInventario: AlertaInventario[];
  syncErp: SyncErpEstado;
}

/* ---------- SPEC-008 — Analítica multisectorial ---------- */

export interface CsatMensual {
  mes: string;
  comercial: number;
  servicios: number;
  manufactura: number;
}

export interface AnalyticsData {
  notaFicticia: string;
  csatMensual: CsatMensual[];
}
