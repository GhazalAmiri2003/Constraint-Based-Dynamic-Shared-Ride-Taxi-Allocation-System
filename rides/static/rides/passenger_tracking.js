(function () {
    "use strict";

    const states = {};

    function getState(rideRequestId) {
        return states[Number(rideRequestId)];
    }

    function stopPolling(rideRequestId) {
        const state = getState(rideRequestId);

        if (state && state.timer) {
            clearInterval(state.timer);
            state.timer = null;
        }
    }

    function phaseLabel(value) {
        const labels = {
            WAITING_PICKUP:
                "Taxi is moving toward pickup",
            ONBOARD:
                "Passenger picked up — heading to destination",
            COMPLETED:
                "Ride completed",
            INACTIVE:
                "Ride is no longer active",
            UNKNOWN:
                "Tracking state unavailable",
        };

        return labels[value] || value || "Unknown";
    }

    function updateInfo(
        rideRequestId,
        data
    ) {
        const info = document.getElementById(
            `tracking-info-${rideRequestId}`
        );

        if (!info) return;

        const currentNode = (
            data.vehicle
            && data.vehicle.current_node
                ? data.vehicle.current_node.name
                : "Not available"
        );

        const revision = (
            data.route_revision === null
            || data.route_revision === undefined
                ? ""
                : `
                    <span>
                        <strong>Route revision:</strong>
                        ${PassengerMapCore.escapeHtml(
                            data.route_revision
                        )}
                    </span>
                `
        );

        info.innerHTML = `
            <div class="tracking-info-grid">

                <span>
                    <strong>Ride:</strong>
                    #${PassengerMapCore.escapeHtml(
                        data.ride?.id ?? "-"
                    )}
                </span>

                <span>
                    <strong>Ride status:</strong>
                    ${PassengerMapCore.escapeHtml(
                        data.ride?.status ?? "-"
                    )}
                </span>

                <span>
                    <strong>Taxi:</strong>
                    #${PassengerMapCore.escapeHtml(
                        data.vehicle?.id ?? "-"
                    )}
                </span>

                <span>
                    <strong>Current node:</strong>
                    ${PassengerMapCore.escapeHtml(
                        currentNode
                    )}
                </span>

                <span>
                    <strong>Passenger phase:</strong>
                    ${PassengerMapCore.escapeHtml(
                        phaseLabel(
                            data.passenger_phase
                        )
                    )}
                </span>

                ${revision}

            </div>
        `;
    }

    function ensureEndpointMarkers(
        state,
        data
    ) {
        if (
            !state.pickupMarker
            && data.pickup_node
        ) {
            state.pickupMarker = (
                PassengerMapCore.addPickupMarker(
                    state.map,
                    data.pickup_node
                )
            );
        }

        if (
            !state.destinationMarker
            && data.destination_node
        ) {
            state.destinationMarker = (
                PassengerMapCore.addDestinationMarker(
                    state.map,
                    data.destination_node
                )
            );
        }
    }

    function updateTaxiMarker(
        state,
        data
    ) {
        const currentNode = (
            data.vehicle
            && data.vehicle.current_node
        );

        if (!currentNode) return;

        const popup = `
            <strong>
                Taxi #${PassengerMapCore.escapeHtml(
                    data.vehicle.id
                )}
            </strong>
            <br>
            Current node:
            ${PassengerMapCore.escapeHtml(
                currentNode.name
            )}
            <br>
            Ride status:
            ${PassengerMapCore.escapeHtml(
                data.ride?.status ?? "-"
            )}
        `;

        if (!state.taxiMarker) {
            state.taxiMarker = (
                PassengerMapCore.addTaxiMarker(
                    state.map,
                    currentNode,
                    "T",
                    popup
                )
            );
        } else {
            state.taxiMarker
                .setLatLng(
                    PassengerMapCore.nodePosition(
                        currentNode
                    )
                )
                .bindPopup(popup);
        }
    }

    function updatePath(
        state,
        data
    ) {
        state.pathLine = (
            PassengerMapCore.replacePath(
                state.pathLine,
                state.map,
                state.nodeById,
                data.remaining_path_node_ids || [],
                {
                    weight: 8,
                    opacity: 0.85,
                    dashArray: "12, 7",
                }
            )
        );
    }

    async function refresh(
        rideRequestId
    ) {
        const state = getState(
            rideRequestId
        );

        if (!state) return;

        try {
            const response = await fetch(
                `/api/ride-requests/${rideRequestId}/tracking/`,
                {
                    method: "GET",
                    credentials: "same-origin",
                    cache: "no-store",
                }
            );

            const data = await response.json();

            if (!response.ok) {
                throw new Error(
                    data.detail
                    || "Could not refresh ride tracking."
                );
            }

            if (!data.ride) {
                const info = document.getElementById(
                    `tracking-info-${rideRequestId}`
                );

                if (info) {
                    info.innerHTML = `
                        <p class="text-muted">
                            ${PassengerMapCore.escapeHtml(
                                data.detail
                                || "Waiting for an assigned ride."
                            )}
                        </p>
                    `;
                }

                return;
            }

            updateInfo(
                rideRequestId,
                data
            );

            ensureEndpointMarkers(
                state,
                data
            );

            updateTaxiMarker(
                state,
                data
            );

            updatePath(
                state,
                data
            );

            // Do not stop on REJECTED while the request is
            // PENDING: Increment 5 Recovery may assign a new
            // replacement Ride on a following poll.
            const requestIsTerminal = [
                "COMPLETED",
                "CANCELLED",
            ].includes(
                data.request_status
            );

            const rideIsTerminal = [
                "COMPLETED",
                "CANCELLED",
            ].includes(
                data.ride.status
            );

            if (
                requestIsTerminal
                || rideIsTerminal
            ) {
                stopPolling(
                    rideRequestId
                );
            }
        } catch (error) {
            console.error(error);

            const info = document.getElementById(
                `tracking-info-${rideRequestId}`
            );

            if (info) {
                info.innerHTML = `
                    <p class="shared-error">
                        ${PassengerMapCore.escapeHtml(
                            error.message
                            || "Tracking update failed."
                        )}
                    </p>
                `;
            }
        }
    }

    async function start(
        rideRequestId
    ) {
        const numericId = Number(
            rideRequestId
        );

        if (states[numericId]) {
            states[numericId].map
                .invalidateSize();

            await refresh(numericId);

            if (!states[numericId].timer) {
                states[numericId].timer = (
                    setInterval(
                        () => refresh(numericId),
                        2000
                    )
                );
            }

            return;
        }

        const mapElement = (
            document.getElementById(
                `tracking-map-${numericId}`
            )
        );

        if (!mapElement) return;

        const network = await (
            PassengerMapCore.loadNetwork()
        );

        const base = (
            PassengerMapCore.createBaseMap(
                `tracking-map-${numericId}`,
                network
            )
        );

        states[numericId] = {
            map: base.map,
            nodeById: base.nodeById,
            taxiMarker: null,
            pickupMarker: null,
            destinationMarker: null,
            pathLine: null,
            timer: null,
        };

        await refresh(numericId);

        states[numericId].timer = (
            setInterval(
                () => refresh(numericId),
                2000
            )
        );
    }

    async function toggle(
        rideRequestId
    ) {
        const panel = document.getElementById(
            `ride-tracking-${rideRequestId}`
        );

        if (!panel) return;

        const willShow = (
            panel.hasAttribute("hidden")
        );

        if (willShow) {
            panel.removeAttribute("hidden");

            try {
                await start(
                    rideRequestId
                );

                setTimeout(
                    () => {
                        getState(
                            rideRequestId
                        )?.map
                        .invalidateSize();
                    },
                    100
                );
            } catch (error) {
                console.error(error);

                const info = document.getElementById(
                    `tracking-info-${rideRequestId}`
                );

                if (info) {
                    info.innerHTML = `
                        <p class="shared-error">
                            ${PassengerMapCore.escapeHtml(
                                error.message
                            )}
                        </p>
                    `;
                }
            }
        } else {
            panel.setAttribute(
                "hidden",
                ""
            );

            stopPolling(
                rideRequestId
            );
        }
    }

    window.PassengerTracking = {
        toggle,
        start,
        refresh,
        stop: stopPolling,
    };
})();
