export function HighlightedText({ text, query }: { text: string; query: string }) {
  const terms = query.trim().length >= 2 ? query.trim().split(/\s+/).filter(Boolean) : []
  if (!terms.length) return text
  const pattern = new RegExp(`(${terms.map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi')
  return text.split(pattern).map((part, index) =>
    index % 2 ? (
      <mark className="content-hit-mark" key={index}>
        {part}
      </mark>
    ) : (
      part
    )
  )
}
