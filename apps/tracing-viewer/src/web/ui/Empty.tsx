export function Empty({ title, copy }: { title: string; copy?: string }) {
  return (
    <div className="empty-state">
      <p className="empty-title">{title}</p>
      {copy && <p className="empty-copy">{copy}</p>}
    </div>
  )
}
