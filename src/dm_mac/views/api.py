"""API Views."""

from logging import Logger
from logging import getLogger
from typing import Tuple

from quart import Blueprint
from quart import Response
from quart import current_app
from quart import jsonify
from quart_schema import document_response
from quart_schema import tag

from dm_mac.models.api_schemas import ApiIndexResponse
from dm_mac.models.api_schemas import ErrorResponse
from dm_mac.models.api_schemas import MachinesListResponse
from dm_mac.models.api_schemas import ReloadUsersResponse
from dm_mac.models.machine import MachinesConfig
from dm_mac.models.users import UsersConfig

logger: Logger = getLogger(__name__)

api: Blueprint = Blueprint("api", __name__, url_prefix="/api")


@api.route("/")
@tag(["Admin"])
@document_response(ApiIndexResponse, 200)
async def index() -> Tuple[Response, int]:
    """API index route.

    Returns a placeholder message.
    """
    return jsonify({"message": "Nothing to see here..."}), 200


@api.route("/machines")
@tag(["Admin"])
@document_response(MachinesListResponse, 200)
async def machines() -> Tuple[Response, int]:
    """List all machines and their current status.

    Read-only endpoint returning the status of every configured machine,
    sorted by name. Intended for external consumers (e.g. the Equipment
    Status Board) to poll or reconcile machine state.
    """
    mconf: MachinesConfig = current_app.config["MACHINES"]  # noqa
    machine_list = [
        mconf.machines_by_name[name].status_dict
        for name in sorted(mconf.machines_by_name)
    ]
    return jsonify({"machines": machine_list}), 200


@api.route("/reload-users", methods=["POST"])
@tag(["Admin"])
@document_response(ReloadUsersResponse, 200)
@document_response(ErrorResponse, 500)
async def reload_users() -> Tuple[Response, int]:
    """Reload users configuration.

    Hot-reloads users.json without requiring a server restart.
    Returns counts of removed, updated, and added users.
    """
    added: int
    updated: int
    removed: int
    try:
        users: UsersConfig = current_app.config["USERS"]  # noqa
        removed, updated, added = users.reload()
        return jsonify({"removed": removed, "updated": updated, "added": added}), 200
    except Exception as ex:
        logger.error("Error reloading users config: %s", ex, exc_info=True)
        return jsonify({"error": str(ex)}), 500
