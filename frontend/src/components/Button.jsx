export default function Button({ as: Component = "button", variant = "primary", className = "", children, ...props }) {
  const variants = {
    primary: "border-teal-200/40 bg-gradient-to-r from-teal-200 to-emerald-200 text-black shadow-[0_0_22px_rgba(45,212,191,0.16)] hover:from-teal-100 hover:to-emerald-100",
    secondary: "border-white/10 bg-white/[0.065] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] hover:border-white/16 hover:bg-white/[0.1]",
    danger: "border-rose-300/20 bg-rose-400/10 text-rose-100 hover:border-rose-300/30 hover:bg-rose-400/20",
    ghost: "border-transparent bg-transparent text-zinc-300 hover:bg-white/[0.06] hover:text-white",
  };

  return (
    <Component
      className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border px-4 py-2 text-sm font-semibold transition duration-200 disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}
      {...props}
    >
      {children}
    </Component>
  );
}
