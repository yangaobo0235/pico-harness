import { createElement, Fragment, useMemo, type ReactNode } from 'react'

// Descriptor templates produce escaped, presentational markup. Convert the permitted
// vocabulary to React nodes; executable HTML, arbitrary attributes and URLs are discarded.
const tags = new Set([
  'div',
  'article',
  'header',
  'section',
  'h3',
  'h4',
  'h5',
  'strong',
  'span',
  'p',
  'pre',
  'code',
  'br',
  'details',
  'summary',
  'button',
  'table',
  'thead',
  'tbody',
  'tr',
  'td',
  'th',
  'ul',
  'ol',
  'li',
  'em',
  'small',
  'mark',
  'dl',
  'dt',
  'dd'
])
export function FormattedContent({
  markup,
  query = '',
  openKeys,
  onToggle
}: {
  markup: string
  query?: string
  openKeys: Set<string>
  onToggle(key: string, open: boolean): void
}) {
  const nodes = useMemo(() => {
    const document = new DOMParser().parseFromString(markup, 'text/html')
    const terms = query.trim().length >= 2 ? query.trim().split(/\s+/).filter(Boolean) : []
    const pattern = terms.length
      ? new RegExp(`(${terms.map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi')
      : null
    function convert(node: Node, key: string): ReactNode {
      if (node.nodeType === Node.TEXT_NODE) {
        const text = node.textContent || ''
        return pattern
          ? text.split(pattern).map((part, i) =>
              i % 2 ? (
                <mark className="content-hit-mark" key={`${key}:${i}`}>
                  {part}
                </mark>
              ) : (
                part
              )
            )
          : text
      }
      if (!(node instanceof HTMLElement)) return null
      const tag = node.tagName.toLowerCase()
      if (!tags.has(tag)) return null
      const props: Record<string, unknown> = { key }
      for (const { name, value } of Array.from(node.attributes)) {
        if (name === 'class') props.className = value
        else if (name === 'title' || name.startsWith('data-') || name.startsWith('aria-')) props[name] = value
        else if (name === 'colspan') props.colSpan = Number(value)
      }
      if (tag === 'button') props.type = 'button'
      if (tag === 'details') {
        const detailKey = node.dataset.detailKey || key
        props.open = openKeys.has(detailKey)
        props.onToggle = (event: { currentTarget: HTMLDetailsElement }) => onToggle(detailKey, event.currentTarget.open)
      }
      return createElement(tag, props, ...Array.from(node.childNodes).map((child, i) => convert(child, `${key}.${i}`)))
    }
    return Array.from(document.body.childNodes).map((node, i) => convert(node, String(i)))
  }, [markup, query, openKeys, onToggle])
  return <Fragment>{nodes}</Fragment>
}
