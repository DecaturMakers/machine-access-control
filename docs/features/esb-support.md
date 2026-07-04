# Feature Template

You must read, understand, and follow all instructions in `./README.md` when planning and implementing this feature.

## Overview

Goal: implement the required minimal changes in this application to support https://github.com/DecaturMakers/equipment-status-board/issues/10.

At a high level, this means:

1. If we don't already have one, a simple API for retrieving a list of all machines and their current status.
2. Ability to fire a webhook (non-blocking/async or from a background worker) when a machine's status is changed (user login/logout, unauthorized RFID fob, oops/lockout/clear), using a webhook destination configured via environment variable. The webhook should include information on the currently-logged-in user if there is one. This should only fire on meaningful status changes, not on every update from the MCU.
3. If we don't already have them, API endpoints to oops a machine, put it in maintenance lockout, or clear oops/lockout.

Our approach is to minimize change in this application, and let ESB do the heavy lifting; we just need to send events to it via webhook and give it the appropriate API endpoints to call.
