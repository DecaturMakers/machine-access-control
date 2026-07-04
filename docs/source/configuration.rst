.. _configuration:

Configuration
=============

Configuration of the machine-access-control (MAC) server is accomplished by some JSON configuration files and optional environment variables, as detailed below.

.. _configuration.users-json:

users.json
----------

Users are configured via a ``users.json`` file in the current directory, or another file name/path specified in the ``USERS_CONFIG`` environment variable. This file defines all of the users and their contact information, as well as their RFID fob code(s) and the authorizations/trainings they have. If using the Neon One CRM, this file can be auto-generated from your CRM Accounts via the :ref:`neon`.

Each user may optionally include an ``oops_override`` boolean field (defaults to ``false``). When set to ``true``, the user can activate machines that are oopsed or locked out without clearing those states. This is intended for designated repair members who need to test machines without generating confusing Slack notifications. Existing ``users.json`` files without this field remain fully compatible.

The schema of this file is as follows:

.. jsonschema:: dm_mac.models.users.CONFIG_SCHEMA

.. _configuration.machines-json:

machines.json
-------------

Machines are configured via a ``machines.json`` file in the current directory, or another file name/path specified in the ``MACHINES_CONFIG`` environment variable. This file lists all of the supported/configured machines and which authorization(s) are required to use them. Note that the names in this file must match the names configured in your ESPHome :ref:`hardware`. Machine names must be unqiue and can only contain alphanumeric characters, underscores, and dashes. No spaces, no dots.

Each machine configuration supports an optional ``alias`` field, which provides a human-friendly name for the machine. When present, the alias will be used in Slack messages and log output instead of the machine name. Both the machine name and alias can be used in incoming Slack commands.

The schema of this file is as follows:

.. jsonschema:: dm_mac.models.machine.CONFIG_SCHEMA

.. _configuration.machines-json.second_relay:

Second Relay (``second_relay``) — Optional
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Each machine entry may optionally include a ``second_relay`` block to enable an additional output relay (driven by GPIO14 / V1 connector pin 6) gated on a separate authorization. This is useful for machines that have an accessory (for example a laser cutter rotary attachment) that requires its own training.

The second relay only energizes when (a) the primary relay is already energized for the current operator AND (b) the operator additionally satisfies the ``second_relay`` rules.

The block accepts the following options:

* ``authorizations_or`` (required, non-empty list of strings) — operator must hold any one of these to energize the second relay
* ``unauthorized_warn_only`` (optional bool, default ``false``) — energize the second relay even for primary-authorized operators lacking the secondary auth, but emit a warning log + Slack message
* ``always_enabled`` (optional bool, default ``false``) — second relay tracks the primary relay's energized state regardless of operator's secondary authorization
* ``alias`` (optional string) — human-readable name for the accessory governed by the second relay; used in Slack/log lines that refer specifically to second-relay events

The LCD content is intentionally not modified by ``second_relay`` configuration; operators learn the accessory state from the physical accessory itself.

Example::

    {
      "laser_cutter": {
        "authorizations_or": ["laser_basic"],
        "alias": "Laser Cutter",
        "second_relay": {
          "authorizations_or": ["laser_rotary"],
          "alias": "Rotary Attachment"
        }
      }
    }

Adding, removing, or modifying a ``second_relay`` block requires a server restart, same as other ``machines.json`` changes.

.. _configuration.env-vars:

Environment Variables
---------------------

.. list-table:: Environment Variables
   :header-rows: 1

   * - Variable
     - Required?
     - Description
   * - ``USERS_CONFIG``
     - no
     - path to users configuration file; default ``./users.json``
   * - ``MACHINES_CONFIG``
     - no
     - path to machines configuration file; default ``./machines.json``
   * - ``MACHINE_STATE_DIR``
     - no
     - path to machine state directory; default ``./machine_state``
   * - ``SLACK_BOT_TOKEN``
     - no
     - If using the Slack integration, the Bot User OAuth Token for your installation of the app.
   * - ``SLACK_APP_TOKEN``
     - no
     - If using the Slack integration, the Socket OAuth Token for your installation of the app.
   * - ``SLACK_SIGNING_SECRET``
     - no
     - If using the Slack integration, the Signing Secret for your installation of the app.
   * - ``SLACK_CONTROL_CHANNEL_ID``
     - no
     - If using the Slack integration, the Channel ID of of the private channel for admins to control MAC.
   * - ``SLACK_OOPS_CHANNEL_ID``
     - no
     - If using the Slack integration, the Channel ID of of the public channel where Oops and maintenance notices will be posted, and where machine status can be checked.
   * - ``STATUS_WEBHOOK_URL``
     - no
     - If set, the URL to POST a JSON status-change webhook to on every meaningful machine event (login, logout, unauthorized or unknown fob, override login, oops, un-oops, lockout, unlock, reboot). Disabled when unset. See :ref:`http-api.status-webhook`.

.. _configuration.machine-state-dir:

Machine State Directory
-----------------------

During operation, the state of each machine is cached on disk every time it's updated; this is done to ensure that a restart of the server will not affect running machines. As of this time, state is saved to a separate file for each machine. By default, these are saved in a ``machine_state`` subdirectory of the current directory, which is created if it does not exist. An alternate directory to save machine state to can be specified via the ``MACHINE_STATE_DIR`` environment variable.
