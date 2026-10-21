import { describe, expect, it } from 'vitest'

import { padVerb, VERB_PAD_LEN } from '../../../src/app/components/appChrome.js'
import { VERBS } from '../../../src/shared/content/verbs.js'

describe('FaceTicker verb padding', () => {
  it('pads every verb to the same width', () => {
    for (const verb of VERBS) {
      expect(padVerb(verb)).toHaveLength(VERB_PAD_LEN)
    }
  })

  it('keeps trailing ellipsis attached', () => {
    for (const verb of VERBS) {
      expect(padVerb(verb).startsWith(`${verb}…`)).toBe(true)
    }
  })
})
