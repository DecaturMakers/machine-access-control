HTTP API
========

This page documents the HTTP API exposed by the MAC server.

The OpenAPI spec is also available at ``/openapi.json`` on a running server,
with interactive documentation at ``/docs`` (Swagger UI) and ``/redocs`` (ReDoc).

.. openapi:: openapi.json

State Save Timeout (HTTP 503)
-----------------------------

The endpoints that mutate machine state —

* ``POST /api/machine/update``,
* ``POST /api/machine/oops/<machine_name>`` and
  ``DELETE /api/machine/oops/<machine_name>``,
* ``POST /api/machine/locked_out/<machine_name>`` and
  ``DELETE /api/machine/locked_out/<machine_name>``

— bound the time spent persisting state to disk to
``STATE_SAVE_TIMEOUT_SEC`` (2.0 seconds). If the underlying disk hangs
and the write exceeds this budget, the handler returns:

For ``POST /api/machine/update`` (firmware-facing):

::

    HTTP/1.1 503 Service Unavailable
    Content-Type: application/json

    {"error": "state save timeout"}

For the admin endpoints (``POST/DELETE`` on ``/api/machine/oops/<name>``
and ``/api/machine/locked_out/<name>``), the response body includes
``action_applied: true`` to indicate that the requested state mutation
took effect in memory even though persistence timed out — these
actions also send Slack notifications in a fire-and-forget fashion,
which cannot be rolled back, so the action *is* live and the next
successful save will catch up:

::

    HTTP/1.1 503 Service Unavailable
    Content-Type: application/json

    {"error": "state save timeout", "action_applied": true}

For the firmware-facing endpoint, the 503 response is the recommended
path for the MCU to recover from a stuck disk on the server: it sees a
clean error, leaves its current relay state alone, and retries on its
next 10-second heartbeat. Without this bound, a slow-but-eventually
successful 200 response can wedge the firmware via ESPHome
``http_request`` issues such as `#6677
<https://github.com/esphome/issues/issues/6677>`_.

Each timeout increments the per-machine ``mac_state_save_timeouts_total``
Prometheus counter. A Slack notification is posted to
``SLACK_CONTROL_CHANNEL_ID`` *exactly once*, on the transition from 1
to 2 lifetime timeouts for a given machine; subsequent timeouts under a
sustained disk hang do not re-page (operators monitoring the Prometheus
counter can alert on continued growth).

Second Relay Protocol Additions
-------------------------------

``POST /api/machine/update`` accepts an optional additive request field and emits
an additive response field to support the per-machine ``second_relay``
configuration (see :ref:`configuration.machines-json.second_relay`):

* Request — ``second_relay_state`` (boolean, optional): The actual current
  state of the second relay as known to the MCU. Reported by firmware that
  drives a second relay; older firmware omits this field. The server uses
  this for observability only and never for authorization decisions.
* Response — ``second_relay`` (boolean, always emitted, defaults to
  ``false``): Desired state of the second relay. For machines without
  ``second_relay`` configured this is always ``false``. Firmware that does
  not know about this field simply ignores it.

The ``display`` field is byte-identical between pre-feature and post-feature
servers for any given (machine, operator, machine state) tuple. ``second_relay``
configuration never causes LCD changes.

Machine Status API
------------------

``GET /api/machines``

Returns the current status of every configured machine as JSON, sorted by
machine name. This read-only endpoint is intended for external consumers (such
as the `Equipment Status Board
<https://github.com/DecaturMakers/equipment-status-board>`_) to poll or
reconcile machine state. It is included in the OpenAPI spec above. Each machine
entry has the shape:

::

    {
      "name": "planer",
      "display_name": "Planer",
      "status": "in_use",
      "relay": true,
      "oops": false,
      "locked_out": false,
      "current_user": {"account_id": "123", "full_name": "Jane Doe"},
      "last_checkin": 1720000000.0,
      "last_update": 1720000000.0
    }

``status`` is a derived summary — one of ``locked_out``, ``oops``, ``in_use``,
``idle``, or ``unknown`` (never checked in). ``current_user`` is ``null`` when
no user is logged in. ``last_checkin`` and ``last_update`` are epoch seconds:
``last_checkin`` is ``null`` until the machine's first check-in, and
``last_update`` is ``null`` until its first *meaningful* state change. These are
independent — a machine that has only sent idle heartbeats has a ``last_checkin``
while ``last_update`` is still ``null``.

.. _http-api.status-webhook:

Status-Change Webhook
---------------------

When the ``STATUS_WEBHOOK_URL`` environment variable is set (see
:ref:`configuration.env-vars`), the server POSTs a JSON webhook to that URL on
every *meaningful* machine status change — never on ordinary MCU heartbeats.
This lets an external consumer (such as the Equipment Status Board) maintain
its own activity history and live status without polling.

The webhook fires for these ``event`` values: ``login``, ``logout``,
``unauthorized`` (known user lacking authorization), ``unknown_fob``,
``override_login``, ``oops``, ``unoops``, ``lockout``, ``unlock``, and
``reboot`` (MCU reboot detected).

The request body is the same per-machine object as ``GET /api/machines`` (so
``current_user`` means the same thing) plus three fields:

* ``event`` — the status-change event name (see above).
* ``timestamp`` — epoch seconds when the event fired.
* ``user`` — the user *involved in this event* (the actor), as
  ``{"account_id", "full_name"}`` or ``null``. This differs from
  ``current_user`` for events like ``logout`` and ``unauthorized`` where a user
  acted but is not (or is no longer) logged in.

::

    POST <STATUS_WEBHOOK_URL>
    Content-Type: application/json

    {
      "name": "planer",
      "display_name": "Planer",
      "status": "idle",
      "relay": false,
      "oops": false,
      "locked_out": false,
      "current_user": null,
      "last_checkin": 1720000000.0,
      "last_update": 1720000000.5,
      "event": "logout",
      "timestamp": 1720000000.5,
      "user": {"account_id": "123", "full_name": "Jane Doe"}
    }

Delivery is fire-and-forget so it never blocks the MCU response: each webhook
is sent on a background task that retries with exponential backoff and a
per-attempt timeout, giving up (and logging an error) after a few attempts. No
authentication header is sent. Consumers should treat delivery as best-effort
and reconcile via ``GET /api/machines`` when needed. See
:py:mod:`dm_mac.webhook` for details.

Prometheus Metrics
------------------

``GET /metrics``

Returns Prometheus-compatible metrics in ``text/plain`` format. This endpoint
is not included in the OpenAPI spec as it does not return JSON.

For machines with ``second_relay`` configured, the following additional
metrics are emitted (one sample per machine, with labels ``machine_name``,
``display_name``, and ``second_relay_alias``):

* ``machine_second_relay_state`` — whether the second relay is currently
  energized (0/1)
* ``machine_second_relay_configured`` — always ``1`` for machines with a
  ``second_relay`` block
* ``machine_second_relay_unauth_warn_only`` — the ``unauthorized_warn_only``
  config flag (0/1)
* ``machine_second_relay_always_enabled`` — the ``always_enabled`` config
  flag (0/1)

These metrics are not emitted at all for machines without ``second_relay``,
keeping cardinality minimal.

The ``mac_state_save_timeouts_total`` counter (one sample per machine)
exposes the lifetime count of writes to the per-machine pickle that
exceeded ``STATE_SAVE_TIMEOUT_SEC``. See `State Save Timeout (HTTP 503)`_
above for the firmware-facing behavior.

See :py:mod:`dm_mac.views.prometheus` for details on the available metrics.
