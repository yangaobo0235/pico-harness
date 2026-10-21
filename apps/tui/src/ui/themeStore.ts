import { atom } from 'nanostores'

import { DEFAULT_THEME } from './theme.js'

// UI primitives subscribe only to the active presentation theme.
export const $uiTheme = atom(DEFAULT_THEME)
