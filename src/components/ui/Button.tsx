import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";

const buttonVariants = cva(
  [
    "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium",
    "transition-colors duration-fast ease-standard",
    "disabled:pointer-events-none disabled:opacity-50",
    "focus-visible:outline-none focus-visible:shadow-focus",
  ].join(" "),
  {
    variants: {
      variant: {
        primary: "bg-accent-indigo text-text-inverse hover:bg-accent-indigo-strong",
        secondary:
          "bg-bg-surface-raised text-text-primary border border-border-default hover:border-accent-indigo",
        ghost: "bg-transparent text-text-secondary hover:bg-bg-surface-raised",
        danger: "bg-state-danger text-text-inverse hover:bg-state-danger-strong",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-10 px-4",
        lg: "h-12 px-6 text-md",
        icon: "h-10 w-10 p-0",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";
