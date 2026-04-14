import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/shared/lib/cn";

const buttonVariants = cva(
  [
    "inline-flex items-center justify-center rounded-xl text-sm font-semibold",
    "transition-all duration-300 ease-out",
    "motion-safe:active:scale-[0.97] motion-safe:hover:-translate-y-0.5",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-surge/60 focus-visible:ring-offset-2 focus-visible:ring-offset-white",
    "disabled:pointer-events-none disabled:opacity-50 disabled:shadow-none disabled:translate-y-0",
  ].join(" "),
  {
    variants: {
      variant: {
        primary:
          "bg-gradient-to-br from-surge via-surge to-sky-700 text-white shadow-[0_10px_28px_-8px_rgba(14,116,188,0.55)] hover:shadow-[0_14px_36px_-10px_rgba(14,116,188,0.62)] hover:brightness-[1.03]",
        secondary:
          "bg-white/80 text-graphite border border-ink/12 shadow-[0_6px_20px_-12px_rgba(15,23,42,0.35)] backdrop-blur-sm hover:bg-white hover:border-ink/18 hover:shadow-[0_10px_28px_-14px_rgba(15,23,42,0.28)]",
        ghost: "bg-transparent text-ocean hover:bg-ocean/[0.08] hover:shadow-none"
      },
      size: {
        md: "h-10 px-4 py-2",
        sm: "h-8 px-3 py-1.5",
        lg: "h-11 px-5 py-2.5"
      }
    },
    defaultVariants: {
      variant: "primary",
      size: "md"
    }
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return <Comp className={cn(buttonVariants({ variant, size }), className)} ref={ref} {...props} />;
  }
);
Button.displayName = "Button";
