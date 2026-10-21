// AUTO-GENERATED — DO NOT EDIT — run `npm run gen:contracts`.
import Ajv from 'ajv'
import type * as Contracts from './generated.js'

const schema = {
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "TracingContracts",
  "type": "object",
  "properties": {
    "Span": {
      "$ref": "#/definitions/Span"
    },
    "SpanNode": {
      "$ref": "#/definitions/SpanNode"
    },
    "Trace": {
      "$ref": "#/definitions/Trace"
    },
    "TraceSession": {
      "$ref": "#/definitions/TraceSession"
    },
    "LogWindow": {
      "$ref": "#/definitions/LogWindow"
    },
    "TraceData": {
      "$ref": "#/definitions/TraceData"
    },
    "Artifact": {
      "$ref": "#/definitions/Artifact"
    },
    "Descriptor": {
      "$ref": "#/definitions/Descriptor"
    },
    "DescriptorsResponse": {
      "$ref": "#/definitions/DescriptorsResponse"
    },
    "SearchHit": {
      "$ref": "#/definitions/SearchHit"
    },
    "SearchResponse": {
      "$ref": "#/definitions/SearchResponse"
    },
    "HealthResponse": {
      "$ref": "#/definitions/HealthResponse"
    },
    "ShutdownResponse": {
      "$ref": "#/definitions/ShutdownResponse"
    }
  },
  "additionalProperties": false,
  "definitions": {
    "Span": {
      "type": "object",
      "properties": {
        "spanId": {
          "type": "string"
        },
        "traceId": {
          "type": "string"
        },
        "traceKey": {
          "type": [
            "string",
            "null"
          ]
        },
        "parentSpanId": {
          "type": [
            "string",
            "null"
          ]
        },
        "name": {
          "type": "string"
        },
        "kind": {
          "type": "string"
        },
        "startTime": {
          "type": "string"
        },
        "endTime": {
          "type": [
            "string",
            "null"
          ]
        },
        "durationMs": {
          "type": "number"
        },
        "status": {
          "type": "object",
          "properties": {
            "code": {
              "type": [
                "string",
                "number",
                "null"
              ]
            },
            "message": {
              "type": [
                "string",
                "null"
              ]
            }
          },
          "additionalProperties": true
        },
        "isFailed": {
          "type": "boolean"
        },
        "failureLabel": {
          "type": "string"
        },
        "attributes": {
          "type": "object",
          "additionalProperties": true
        },
        "events": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "time": {
                "type": "string"
              },
              "name": {
                "type": "string"
              }
            },
            "required": [
              "time",
              "name"
            ],
            "additionalProperties": true
          }
        },
        "sessionId": {
          "type": [
            "string",
            "null"
          ]
        },
        "sessionKey": {
          "type": [
            "string",
            "null"
          ]
        },
        "agentId": {
          "type": [
            "string",
            "null"
          ]
        },
        "workspaceDir": {
          "type": [
            "string",
            "null"
          ]
        },
        "runId": {
          "type": [
            "string",
            "null"
          ]
        },
        "trigger": {
          "type": [
            "string",
            "null"
          ]
        },
        "channelId": {
          "type": [
            "string",
            "null"
          ]
        },
        "displayTitle": {
          "type": "string"
        },
        "displaySubtitle": {},
        "displayParentSpanId": {
          "type": [
            "string",
            "null"
          ]
        }
      },
      "required": [
        "spanId",
        "traceId",
        "name",
        "kind",
        "startTime",
        "durationMs",
        "status",
        "isFailed",
        "failureLabel",
        "attributes",
        "events",
        "displayTitle",
        "displaySubtitle"
      ],
      "additionalProperties": true
    },
    "SpanNode": {
      "allOf": [
        {
          "$ref": "#/definitions/Span"
        },
        {
          "type": "object",
          "properties": {
            "depth": {
              "type": "number"
            },
            "children": {
              "type": "array",
              "items": {
                "$ref": "#/definitions/SpanNode"
              }
            }
          },
          "required": [
            "depth",
            "children"
          ],
          "additionalProperties": true
        }
      ]
    },
    "Trace": {
      "type": "object",
      "properties": {
        "traceKey": {
          "type": "string"
        },
        "traceId": {
          "type": "string"
        },
        "sessionId": {
          "type": "string"
        },
        "sessionKey": {
          "type": [
            "string",
            "null"
          ]
        },
        "agentId": {
          "type": [
            "string",
            "null"
          ]
        },
        "workspaceDir": {
          "type": [
            "string",
            "null"
          ]
        },
        "trigger": {
          "type": [
            "string",
            "null"
          ]
        },
        "channelId": {
          "type": [
            "string",
            "null"
          ]
        },
        "startTime": {
          "type": "string"
        },
        "endTime": {
          "type": [
            "string",
            "null"
          ]
        },
        "durationMs": {
          "type": "number"
        },
        "spanCount": {
          "type": "number"
        },
        "visibleSpanCount": {
          "type": "number"
        },
        "spans": {
          "type": "array",
          "items": {
            "$ref": "#/definitions/Span"
          }
        },
        "tree": {
          "type": "array",
          "items": {
            "$ref": "#/definitions/SpanNode"
          }
        },
        "events": {
          "type": "array",
          "items": {
            "type": "object"
          }
        }
      },
      "required": [
        "traceKey",
        "traceId",
        "sessionId",
        "sessionKey",
        "agentId",
        "workspaceDir",
        "trigger",
        "channelId",
        "startTime",
        "endTime",
        "durationMs",
        "spanCount",
        "visibleSpanCount",
        "spans",
        "tree",
        "events"
      ],
      "additionalProperties": true
    },
    "TraceSession": {
      "type": "object",
      "properties": {
        "sessionId": {
          "type": "string"
        },
        "sessionKey": {
          "type": [
            "string",
            "null"
          ]
        },
        "agentId": {
          "type": [
            "string",
            "null"
          ]
        },
        "workspaceDir": {
          "type": [
            "string",
            "null"
          ]
        },
        "trigger": {
          "type": [
            "string",
            "null"
          ]
        },
        "channelId": {
          "type": [
            "string",
            "null"
          ]
        },
        "resumedFrom": {
          "type": [
            "string",
            "null"
          ]
        },
        "resumedTo": {
          "type": [
            "string",
            "null"
          ]
        },
        "startedAt": {
          "type": [
            "string",
            "null"
          ]
        },
        "updatedAt": {
          "type": [
            "string",
            "null"
          ]
        },
        "traceCount": {
          "type": "number"
        },
        "traces": {
          "type": "array",
          "items": {
            "$ref": "#/definitions/Trace"
          }
        }
      },
      "required": [
        "sessionId",
        "sessionKey",
        "agentId",
        "workspaceDir",
        "trigger",
        "channelId",
        "resumedFrom",
        "resumedTo",
        "startedAt",
        "updatedAt",
        "traceCount",
        "traces"
      ],
      "additionalProperties": true
    },
    "LogWindow": {
      "type": "object",
      "properties": {
        "bytesRead": {
          "type": "number"
        },
        "maxBytes": {
          "type": "number"
        },
        "filesRead": {
          "type": "number"
        },
        "filesAvailable": {
          "type": "number"
        },
        "records": {
          "type": "number"
        },
        "truncated": {
          "type": "boolean"
        }
      },
      "required": [
        "bytesRead",
        "maxBytes",
        "filesRead",
        "filesAvailable",
        "records",
        "truncated"
      ],
      "additionalProperties": true
    },
    "TraceData": {
      "type": "object",
      "properties": {
        "generatedAt": {
          "type": "string"
        },
        "sessions": {
          "type": "array",
          "items": {
            "$ref": "#/definitions/TraceSession"
          }
        },
        "window": {
          "type": "object",
          "properties": {
            "truncated": {
              "type": "boolean"
            },
            "spans": {
              "$ref": "#/definitions/LogWindow"
            },
            "events": {
              "$ref": "#/definitions/LogWindow"
            }
          },
          "required": [
            "truncated",
            "spans",
            "events"
          ],
          "additionalProperties": true
        }
      },
      "required": [
        "generatedAt",
        "sessions",
        "window"
      ],
      "additionalProperties": true
    },
    "Artifact": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string"
        },
        "content": {
          "type": "string"
        },
        "parsed": {}
      },
      "required": [
        "path",
        "content",
        "parsed"
      ],
      "additionalProperties": true
    },
    "Descriptor": {
      "type": "object",
      "properties": {
        "type": {
          "type": "string"
        },
        "label": {
          "type": "string"
        },
        "subtitle": {
          "type": "string"
        },
        "render": {
          "type": "string"
        },
        "usage": {
          "type": "boolean"
        },
        "status": {
          "type": "array",
          "items": {
            "type": "object"
          }
        },
        "panels": {
          "type": "array",
          "items": {
            "type": "object"
          }
        }
      },
      "required": [
        "type"
      ],
      "additionalProperties": true
    },
    "DescriptorsResponse": {
      "type": "object",
      "properties": {
        "descriptors": {
          "type": "array",
          "items": {
            "$ref": "#/definitions/Descriptor"
          }
        }
      },
      "required": [
        "descriptors"
      ],
      "additionalProperties": true
    },
    "SearchHit": {
      "type": "object",
      "properties": {
        "sessionId": {
          "type": "string"
        },
        "traceKey": {
          "type": "string"
        },
        "traceId": {
          "type": "string"
        },
        "spanId": {
          "type": "string"
        },
        "name": {
          "type": "string"
        },
        "title": {
          "type": "string"
        },
        "startTime": {
          "type": "string"
        },
        "field": {
          "type": "string"
        },
        "snippet": {
          "type": "string"
        },
        "subtitle": {}
      },
      "required": [
        "sessionId",
        "traceKey",
        "traceId",
        "spanId",
        "name",
        "title",
        "startTime",
        "field",
        "snippet"
      ],
      "additionalProperties": true
    },
    "SearchResponse": {
      "type": "object",
      "properties": {
        "results": {
          "type": "array",
          "items": {
            "$ref": "#/definitions/SearchHit"
          }
        }
      },
      "required": [
        "results"
      ],
      "additionalProperties": true
    },
    "HealthResponse": {
      "type": "object",
      "properties": {
        "ok": {
          "const": true
        },
        "port": {
          "type": "number"
        },
        "stateDir": {
          "type": "string"
        }
      },
      "required": [
        "ok",
        "port",
        "stateDir"
      ],
      "additionalProperties": true
    },
    "ShutdownResponse": {
      "type": "object",
      "properties": {
        "ok": {
          "const": true
        },
        "stopping": {
          "const": true
        }
      },
      "required": [
        "ok",
        "stopping"
      ],
      "additionalProperties": true
    }
  }
}
const ajv = new Ajv({ strict: false, allErrors: true })
export const validateSpan = ajv.compile<Contracts.Span>({ definitions: schema.definitions, $ref: '#/definitions/Span' })
export const validateSpanNode = ajv.compile<Contracts.SpanNode>({ definitions: schema.definitions, $ref: '#/definitions/SpanNode' })
export const validateTrace = ajv.compile<Contracts.Trace>({ definitions: schema.definitions, $ref: '#/definitions/Trace' })
export const validateTraceSession = ajv.compile<Contracts.TraceSession>({ definitions: schema.definitions, $ref: '#/definitions/TraceSession' })
export const validateLogWindow = ajv.compile<Contracts.LogWindow>({ definitions: schema.definitions, $ref: '#/definitions/LogWindow' })
export const validateTraceData = ajv.compile<Contracts.TraceData>({ definitions: schema.definitions, $ref: '#/definitions/TraceData' })
export const validateArtifact = ajv.compile<Contracts.Artifact>({ definitions: schema.definitions, $ref: '#/definitions/Artifact' })
export const validateDescriptor = ajv.compile<Contracts.Descriptor>({ definitions: schema.definitions, $ref: '#/definitions/Descriptor' })
export const validateDescriptorsResponse = ajv.compile<Contracts.DescriptorsResponse>({ definitions: schema.definitions, $ref: '#/definitions/DescriptorsResponse' })
export const validateSearchHit = ajv.compile<Contracts.SearchHit>({ definitions: schema.definitions, $ref: '#/definitions/SearchHit' })
export const validateSearchResponse = ajv.compile<Contracts.SearchResponse>({ definitions: schema.definitions, $ref: '#/definitions/SearchResponse' })
export const validateHealthResponse = ajv.compile<Contracts.HealthResponse>({ definitions: schema.definitions, $ref: '#/definitions/HealthResponse' })
export const validateShutdownResponse = ajv.compile<Contracts.ShutdownResponse>({ definitions: schema.definitions, $ref: '#/definitions/ShutdownResponse' })
