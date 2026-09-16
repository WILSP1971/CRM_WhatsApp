import * as RadixTooltip from "@radix-ui/react-tooltip";
import { forwardRef, type ReactNode } from "react";
import { cn } from "@/lib/cn";

export const TooltipProvider = RadixTooltip.Provider;

export const TooltipContent = forwardRef<
  React.ElementRef<typeof RadixTooltip.Content>,
  React.ComponentPropsWithoutRef<typeof RadixTooltip.Content>
>(({ className, sideOffset = 6, ...props }, ref) => (
  <RadixTooltip.Portal>
    <RadixTooltip.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        "z-tooltip rounded-md border border-border-subtle bg-bg-surface-raised px-3 py-1.5",
        "text-xs text-text-primary shadow-md",
        "data-[state=delayed-open]:duration-fast data-[state=delayed-open]:ease-standard",
        className,
      )}
      {...props}
    />
  </RadixTooltip.Portal>
));
TooltipContent.displayName = "TooltipContent";

interface SimpleTooltipProps {
  label: ReactNode;
  children: ReactNode;
}

/**
 * Envoltorio simple y accesible: aparece al hacer hover o al recibir foco de
 * teclado (comportamiento nativo de Radix Tooltip), con `aria-describedby`
 * gestionado automáticamente por Radix.
 */
export function Tooltip({ label, children }: SimpleTooltipProps) {
  return (
    <TooltipProvider delayDuration={200}>
      <RadixTooltip.Root>
        <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
        <TooltipContent>{label}</TooltipContent>
      </RadixTooltip.Root>
    </TooltipProvider>
  );
}
