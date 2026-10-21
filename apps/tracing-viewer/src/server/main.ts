import { applyStateDirArg } from './config/state-dir.js'
applyStateDirArg()
// Configuration must be applied before module-level log paths are selected.
void import('./http/server.js')
