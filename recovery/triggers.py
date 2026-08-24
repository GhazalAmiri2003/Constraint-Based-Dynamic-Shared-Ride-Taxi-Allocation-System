import logging

from django.db import transaction

from recovery.models import RecoveryEvent


logger = logging.getLogger(__name__)


# =========================================================
# Safe Recovery Runner
# =========================================================

def run_recovery_safely(
    *,
    ride_id,
    failed_vehicle_id,
    trigger_type,
):
    """
    Execute Recovery after the original lifecycle
    transaction has successfully committed.

    Recovery failure must NOT undo:

    - Driver Reject
    - Driver Offline
    - Ride state transition

    The RecoveryOrchestrator itself stores FAILED
    RecoveryEvent information when planning/application
    cannot succeed.
    """

    # Local import intentionally avoids circular imports:
    #
    # rides.services
    # -> recovery.triggers
    # -> recovery.orchestrator
    # -> assignment
    # -> rides.services
    from recovery.orchestrator import (
        RecoveryOrchestrator,
        RecoveryOrchestratorError,
    )

    try:

        return (
            RecoveryOrchestrator
            .recover_ride(
                ride_id=ride_id,

                failed_vehicle_id=(
                    failed_vehicle_id
                ),

                trigger_type=(
                    trigger_type
                ),
            )
        )

    except RecoveryOrchestratorError:

        logger.exception(
            (
                "Recovery failed for Ride %s "
                "and Vehicle %s."
            ),
            ride_id,
            failed_vehicle_id,
        )

        return None

    except Exception:

        logger.exception(
            (
                "Unexpected recovery failure for "
                "Ride %s and Vehicle %s."
            ),
            ride_id,
            failed_vehicle_id,
        )

        return None


# =========================================================
# Schedule Recovery After Commit
# =========================================================

def schedule_recovery_on_commit(
    *,
    ride_id,
    failed_vehicle_id,
    trigger_type,
):
    """
    Recovery starts only after the lifecycle transaction
    has successfully committed.
    """

    transaction.on_commit(

        lambda: run_recovery_safely(
            ride_id=ride_id,

            failed_vehicle_id=(
                failed_vehicle_id
            ),

            trigger_type=(
                trigger_type
            ),
        )
    )


# =========================================================
# Driver Reject
# =========================================================

def schedule_driver_reject_recovery(
    *,
    ride_id,
    failed_vehicle_id,
):

    schedule_recovery_on_commit(
        ride_id=ride_id,

        failed_vehicle_id=(
            failed_vehicle_id
        ),

        trigger_type=(
            RecoveryEvent
            .TriggerType
            .DRIVER_REJECT
        ),
    )


# =========================================================
# Driver Unavailable
# =========================================================

def schedule_driver_unavailable_recovery(
    *,
    ride_id,
    failed_vehicle_id,
):

    schedule_recovery_on_commit(
        ride_id=ride_id,

        failed_vehicle_id=(
            failed_vehicle_id
        ),

        trigger_type=(
            RecoveryEvent
            .TriggerType
            .DRIVER_UNAVAILABLE
        ),
    )