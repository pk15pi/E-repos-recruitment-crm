import * as Dialog from "@radix-ui/react-dialog";
import * as LabelPrimitive from "@radix-ui/react-label";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { X } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";

import { cn } from "../lib/cn";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-accent text-white hover:bg-[#0b584c]",
        outline: "border border-line bg-card text-ink hover:bg-paper",
        ghost: "text-ink hover:bg-black/5",
        danger: "bg-danger text-white hover:bg-[#742626]",
      },
      size: {
        default: "h-10 px-4",
        sm: "h-8 px-3 text-xs",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants> & { asChild?: boolean }
>(({ className, variant, size, asChild, ...props }, ref) => {
  const Comp = asChild ? Slot : "button";
  return <Comp ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />;
});
Button.displayName = "Button";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn(
      "h-10 w-full rounded-md border border-line bg-card px-3 text-sm text-ink placeholder:text-muted",
      className,
    )}
    {...props}
  />
));
Input.displayName = "Input";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn("min-h-28 w-full rounded-md border border-line bg-card px-3 py-2 text-sm text-ink", className)}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";

export const Label = forwardRef<HTMLLabelElement, React.ComponentProps<typeof LabelPrimitive.Root>>(
  ({ className, ...props }, ref) => (
    <LabelPrimitive.Root ref={ref} className={cn("text-sm font-medium text-ink", className)} {...props} />
  ),
);
Label.displayName = "Label";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={cn("rounded-lg border border-line bg-card p-4 shadow-sm", className)}>{children}</section>;
}

const badgeTone: Record<string, string> = {
  neutral: "bg-paper text-ink",
  good: "bg-accent-soft text-accent",
  warn: "bg-warn-soft text-warn",
  bad: "bg-red-100 text-danger",
};

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: keyof typeof badgeTone }) {
  return <span className={cn("inline-flex rounded-full px-2 py-0.5 text-xs font-medium capitalize", badgeTone[tone])}>{children}</span>;
}

export function DialogRoot({
  open,
  onOpenChange,
  title,
  description,
  children,
  trigger,
}: {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  trigger?: ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      {trigger ? <Dialog.Trigger asChild>{trigger}</Dialog.Trigger> : null}
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-50 max-h-[90vh] w-[min(560px,calc(100%-2rem))] -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-lg border border-line bg-card p-5 shadow-xl">
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="text-2xl">{title}</Dialog.Title>
              {description ? <Dialog.Description className="mt-1 text-sm text-muted">{description}</Dialog.Description> : null}
            </div>
            <Dialog.Close className="rounded-md p-1 hover:bg-paper" aria-label="Close">
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function Select({
  value,
  onChange,
  children,
  label,
  id,
}: {
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
  label?: string;
  id?: string;
}) {
  return (
    <label className="grid gap-1 text-sm" htmlFor={id}>
      {label ? <span className="font-medium">{label}</span> : null}
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 rounded-md border border-line bg-card px-2 text-sm"
      >
        {children}
      </select>
    </label>
  );
}
