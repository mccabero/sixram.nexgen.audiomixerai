export default function EmptyState({ icon: Icon, title, description, action }) {
  return (
    <div className="flex min-h-64 flex-col items-center justify-center rounded-lg border border-dashed border-white/14 bg-white/[0.03] px-6 py-12 text-center">
      {Icon ? (
        <span className="mb-4 grid h-12 w-12 place-items-center rounded-lg border border-white/10 bg-white/[0.05] text-teal-200">
          <Icon size={22} />
        </span>
      ) : null}
      <h2 className="text-lg font-semibold text-white">{title}</h2>
      <p className="mt-2 max-w-xl text-sm leading-6 text-zinc-400">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

