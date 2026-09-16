import { useMemo, useState, useCallback, useRef } from "react";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  closestCenter,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
  sortableKeyboardCoordinates,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ArrowLeft, ArrowRight, GripVertical } from "lucide-react";
import { Badge, Button, Card } from "@/components/ui";
import { cn } from "@/lib/cn";
import { formatCurrency } from "@/lib/format";
import type { EtapaEmbudo, EtapaId, Oportunidad } from "@/lib/sectorTypes";

const STAGE_BADGE_VARIANT: Record<
  EtapaEmbudo["color"],
  "neutral" | "success" | "warning" | "danger" | "ai"
> = {
  muted: "neutral",
  cyan: "ai",
  warning: "warning",
  indigo: "ai",
  success: "success",
  danger: "danger",
};

interface SalesKanbanBoardProps {
  etapas: EtapaEmbudo[];
  oportunidades: Oportunidad[];
}

/**
 * Embudo de ventas Kanban (SPEC-007, RF-07). Arrastrable con dnd-kit
 * (PointerSensor) y con alternativa 100% por teclado: cada tarjeta expone
 * botones "Mover a etapa anterior/siguiente" y responde a flechas cuando
 * tiene el foco (KeyboardSensor de dnd-kit + controles explícitos).
 * Los anuncios de movimiento van a una región `aria-live` para lectores
 * de pantalla.
 */
export function SalesKanbanBoard({ etapas, oportunidades }: SalesKanbanBoardProps) {
  const [items, setItems] = useState<Oportunidad[]>(oportunidades);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const liveRegionTimeout = useRef<ReturnType<typeof setTimeout>>();

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const byStage = useMemo(() => {
    const map = new Map<EtapaId, Oportunidad[]>();
    for (const etapa of etapas) map.set(etapa.id, []);
    for (const op of items) {
      const list = map.get(op.etapaId);
      if (list) list.push(op);
    }
    return map;
  }, [etapas, items]);

  const announce = useCallback((message: string) => {
    setAnnouncement(message);
    if (liveRegionTimeout.current) clearTimeout(liveRegionTimeout.current);
    liveRegionTimeout.current = setTimeout(() => setAnnouncement(""), 4000);
  }, []);

  const moveCard = useCallback(
    (cardId: string, targetEtapaId: EtapaId) => {
      setItems((prev) => {
        const card = prev.find((op) => op.id === cardId);
        if (!card || card.etapaId === targetEtapaId) return prev;
        const targetLabel =
          etapas.find((e) => e.id === targetEtapaId)?.label ?? targetEtapaId;
        announce(`${card.cliente} movida a la etapa ${targetLabel}.`);
        return prev.map((op) =>
          op.id === cardId ? { ...op, etapaId: targetEtapaId } : op,
        );
      });
    },
    [announce, etapas],
  );

  const moveCardRelative = useCallback(
    (cardId: string, direction: -1 | 1) => {
      const card = items.find((op) => op.id === cardId);
      if (!card) return;
      const currentIndex = etapas.findIndex((e) => e.id === card.etapaId);
      const nextIndex = currentIndex + direction;
      if (nextIndex < 0 || nextIndex >= etapas.length) return;
      moveCard(cardId, etapas[nextIndex].id);
    },
    [etapas, items, moveCard],
  );

  function handleDragStart(event: DragStartEvent) {
    setActiveId(String(event.active.id));
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    setActiveId(null);
    if (!over) return;
    const overData = over.data.current as { etapaId?: EtapaId } | undefined;
    const targetEtapaId = overData?.etapaId ?? (over.id as EtapaId);
    if (targetEtapaId) {
      moveCard(String(active.id), targetEtapaId);
    }
  }

  const activeCard = activeId ? items.find((op) => op.id === activeId) : null;

  return (
    <div>
      <p aria-live="polite" className="sr-only">
        {announcement}
      </p>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <div
          role="list"
          aria-label="Embudo de ventas por etapa"
          className="grid grid-cols-1 gap-3 overflow-x-auto pb-2 sm:grid-cols-2 xl:grid-cols-6"
        >
          {etapas.map((etapa) => {
            const cards = byStage.get(etapa.id) ?? [];
            const total = cards.reduce((sum, op) => sum + op.monto, 0);
            return (
              <KanbanColumn
                key={etapa.id}
                etapa={etapa}
                cards={cards}
                total={total}
                etapas={etapas}
                onMoveRelative={moveCardRelative}
              />
            );
          })}
        </div>
        <DragOverlay>
          {activeCard ? (
            <OpportunityCardContent oportunidad={activeCard} dragging />
          ) : null}
        </DragOverlay>
      </DndContext>
    </div>
  );
}

interface KanbanColumnProps {
  etapa: EtapaEmbudo;
  cards: Oportunidad[];
  total: number;
  etapas: EtapaEmbudo[];
  onMoveRelative: (cardId: string, direction: -1 | 1) => void;
}

function KanbanColumn({
  etapa,
  cards,
  total,
  etapas,
  onMoveRelative,
}: KanbanColumnProps) {
  const stageIndex = etapas.findIndex((e) => e.id === etapa.id);
  const cardIds = cards.map((c) => c.id);

  return (
    <div
      role="listitem"
      aria-label={`Etapa ${etapa.label}, ${cards.length} oportunidades`}
      className="flex min-w-[220px] flex-col gap-2 rounded-lg border border-border-subtle bg-bg-surface p-2"
    >
      <div className="flex items-center justify-between px-1">
        <Badge variant={STAGE_BADGE_VARIANT[etapa.color]}>{etapa.label}</Badge>
        <span className="text-xs text-text-muted">{cards.length}</span>
      </div>
      <span className="px-1 text-xs text-text-secondary">{formatCurrency(total)}</span>
      <SortableContext items={cardIds} strategy={verticalListSortingStrategy}>
        <div
          id={etapa.id}
          role="group"
          aria-label={`Tarjetas en ${etapa.label}`}
          className="flex min-h-[60px] flex-col gap-2"
          data-etapa-id={etapa.id}
        >
          {cards.map((oportunidad) => (
            <OpportunityCard
              key={oportunidad.id}
              oportunidad={oportunidad}
              etapaId={etapa.id}
              canMoveLeft={stageIndex > 0}
              canMoveRight={stageIndex < etapas.length - 1}
              prevLabel={stageIndex > 0 ? etapas[stageIndex - 1].label : undefined}
              nextLabel={
                stageIndex < etapas.length - 1 ? etapas[stageIndex + 1].label : undefined
              }
              onMoveRelative={onMoveRelative}
            />
          ))}
          {cards.length === 0 && (
            <p className="rounded-md border border-dashed border-border-subtle p-3 text-center text-xs text-text-muted">
              Sin oportunidades
            </p>
          )}
        </div>
      </SortableContext>
    </div>
  );
}

interface OpportunityCardProps {
  oportunidad: Oportunidad;
  etapaId: EtapaId;
  canMoveLeft: boolean;
  canMoveRight: boolean;
  prevLabel?: string;
  nextLabel?: string;
  onMoveRelative: (cardId: string, direction: -1 | 1) => void;
}

function OpportunityCard({
  oportunidad,
  etapaId,
  canMoveLeft,
  canMoveRight,
  prevLabel,
  nextLabel,
  onMoveRelative,
}: OpportunityCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({
      id: oportunidad.id,
      data: { etapaId },
    });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      role="option"
      aria-roledescription="Tarjeta de oportunidad arrastrable"
      aria-selected={false}
      className={cn(isDragging && "opacity-40")}
    >
      <Card className="flex flex-col gap-2 p-3 focus-within:shadow-focus">
        <div className="flex items-start justify-between gap-2">
          <button
            type="button"
            className={cn(
              "flex flex-1 cursor-grab items-start gap-1.5 text-left",
              "rounded-sm focus-visible:shadow-focus focus-visible:outline-none",
              "active:cursor-grabbing",
            )}
            aria-label={`${oportunidad.cliente}, ${formatCurrency(oportunidad.monto)}, probabilidad ${oportunidad.probabilidad}%. Usa los botones de mover o las flechas para cambiar de etapa.`}
            {...attributes}
            {...listeners}
          >
            <GripVertical
              className="mt-0.5 h-4 w-4 shrink-0 text-text-muted"
              aria-hidden
            />
            <span className="text-sm font-medium text-text-primary">
              {oportunidad.cliente}
            </span>
          </button>
        </div>
        <div className="flex items-center justify-between text-xs text-text-secondary">
          <span>{formatCurrency(oportunidad.monto)}</span>
          <span>{oportunidad.probabilidad}% prob.</span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-text-muted">{oportunidad.responsable}</span>
          <div className="flex gap-1">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              disabled={!canMoveLeft}
              aria-label={
                prevLabel
                  ? `Mover ${oportunidad.cliente} a etapa anterior: ${prevLabel}`
                  : "No hay etapa anterior"
              }
              onClick={() => onMoveRelative(oportunidad.id, -1)}
            >
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              disabled={!canMoveRight}
              aria-label={
                nextLabel
                  ? `Mover ${oportunidad.cliente} a etapa siguiente: ${nextLabel}`
                  : "No hay etapa siguiente"
              }
              onClick={() => onMoveRelative(oportunidad.id, 1)}
            >
              <ArrowRight className="h-3.5 w-3.5" aria-hidden />
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

function OpportunityCardContent({
  oportunidad,
  dragging,
}: {
  oportunidad: Oportunidad;
  dragging?: boolean;
}) {
  return (
    <Card className={cn("flex flex-col gap-2 p-3", dragging && "shadow-lg")}>
      <span className="text-sm font-medium text-text-primary">{oportunidad.cliente}</span>
      <div className="flex items-center justify-between text-xs text-text-secondary">
        <span>{formatCurrency(oportunidad.monto)}</span>
        <span>{oportunidad.probabilidad}% prob.</span>
      </div>
    </Card>
  );
}
