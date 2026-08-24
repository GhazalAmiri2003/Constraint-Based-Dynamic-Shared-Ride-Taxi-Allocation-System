(function () {
    "use strict";

    const POLL_INTERVAL_MS = 2000;

    let map = null;
    let network = null;
    let nodeById = {};
    let dynamicLayer = null;
    let refreshTimer = null;
    let loading = false;

    function core() {
        return window.PassengerMapCore;
    }

    function escapeHtml(value) {
        if (core()) {
            return core().escapeHtml(value);
        }
        return String(value ?? "");
    }

    function statusText(value) {
        return String(value || "-")
            .replaceAll("_", " ");
    }

    function createStopIcon(stop) {
        const isPickup = stop.stop_type === "PICKUP";
        const prefix = isPickup ? "P" : "D";
        const text = `${stop.sequence_number}${prefix}`;

        let className = "driver-map-stop-marker";

        if (stop.status === "COMPLETED") {
            className += " driver-map-stop-completed";
        } else if (stop.status === "CANCELLED") {
            className += " driver-map-stop-cancelled";
        } else if (stop.is_next) {
            className += " driver-map-stop-next";
        } else if (isPickup) {
            className += " driver-map-stop-pickup";
        } else {
            className += " driver-map-stop-dropoff";
        }

        return L.divIcon({
            className: "",
            html: `
                <div class="${className}">
                    ${escapeHtml(text)}
                </div>
            `,
            iconSize: [38, 38],
            iconAnchor: [19, 19],
        });
    }

    function addTaxiMarker(vehicle) {
        if (
            !vehicle
            || !vehicle.current_node
        ) {
            return;
        }

        const node = (
            nodeById[
                Number(vehicle.current_node.id)
            ]
        );

        if (!node) return;

        const marker = core().addTaxiMarker(
            map,
            node,
            "T",
            `
                <strong>My Taxi #${vehicle.id}</strong>
                <br>
                Current node:
                ${escapeHtml(node.name)}
                <br>
                Mode:
                ${escapeHtml(vehicle.ride_mode)}
            `
        );

        dynamicLayer.addLayer(marker);
    }

    function addStopMarker(stop) {
        if (!stop || !stop.node) return;

        const node = (
            nodeById[
                Number(stop.node.id)
            ]
        );

        if (!node) return;

        const marker = L.marker(
            core().nodePosition(node),
            {
                icon: createStopIcon(stop),
                zIndexOffset: (
                    stop.is_next
                    ? 850
                    : 600
                ),
            }
        );

        marker.bindPopup(
            `
                <strong>
                    Stop ${stop.sequence_number}
                    — ${escapeHtml(stop.stop_type)}
                </strong>
                <br>
                Node:
                ${escapeHtml(stop.node.name)}
                <br>
                Passenger:
                ${escapeHtml(stop.passenger_username)}
                <br>
                Passenger count:
                ${escapeHtml(stop.passenger_count)}
                <br>
                Request:
                #${escapeHtml(stop.ride_request_id)}
                <br>
                Status:
                ${escapeHtml(stop.status)}
                ${
                    stop.estimated_arrival_minutes != null
                    ? `
                        <br>
                        ETA:
                        ${escapeHtml(
                            stop.estimated_arrival_minutes
                        )} min
                    `
                    : ""
                }
                ${
                    stop.is_next
                    ? "<br><strong>Next stop</strong>"
                    : ""
                }
            `
        );

        dynamicLayer.addLayer(marker);
    }

    function drawRoutes(activeRide) {
        if (!activeRide) return;

        const remainingPath = (
            activeRide
            .full_remaining_path_node_ids
            || []
        );

        const currentLeg = (
            activeRide
            .current_leg_path_node_ids
            || []
        );

        const remainingLayer = (
            core().drawPath(
                map,
                nodeById,
                remainingPath,
                {
                    weight: 6,
                    opacity: 0.48,
                    dashArray: "10 8",
                }
            )
        );

        if (remainingLayer) {
            dynamicLayer.addLayer(
                remainingLayer
            );
        }

        const currentLayer = (
            core().drawPath(
                map,
                nodeById,
                currentLeg,
                {
                    weight: 8,
                    opacity: 0.9,
                }
            )
        );

        if (currentLayer) {
            dynamicLayer.addLayer(
                currentLayer
            );
        }
    }

    function passengerGroupHtml(group) {
        return `
            <div class="driver-map-passenger">
                <div>
                    <strong>
                        ${escapeHtml(
                            group.passenger_username
                        )}
                    </strong>
                    <span class="status">
                        ${escapeHtml(
                            group.request_status
                        )}
                    </span>
                </div>

                <small>
                    Request #${group.ride_request_id}
                    · ${group.passenger_count}
                    passenger(s)
                    · Pickup ${escapeHtml(
                        group.pickup_node?.name
                    )}
                    · Dropoff ${escapeHtml(
                        group.destination_node?.name
                    )}
                </small>
            </div>
        `;
    }

    function stopHtml(stop) {
        let stateClass = "";

        if (stop.status === "COMPLETED") {
            stateClass = (
                "driver-map-stop-row-completed"
            );
        }

        if (stop.status === "CANCELLED") {
            stateClass = (
                "driver-map-stop-row-cancelled"
            );
        }

        if (stop.is_next) {
            stateClass += (
                " driver-map-stop-row-next"
            );
        }

        return `
            <div class="driver-map-stop-row ${stateClass}">
                <div class="driver-map-stop-order">
                    ${stop.sequence_number}
                </div>

                <div class="driver-map-stop-info">
                    <strong>
                        ${escapeHtml(stop.stop_type)}
                        — ${escapeHtml(stop.node?.name)}
                    </strong>

                    <small>
                        ${escapeHtml(
                            stop.passenger_username
                        )}
                        · ${stop.passenger_count}
                        passenger(s)
                        · Request #${stop.ride_request_id}
                        ${
                            stop.estimated_arrival_minutes != null
                            ? ` · ETA ${stop.estimated_arrival_minutes} min`
                            : ""
                        }
                    </small>
                </div>

                <span class="status">
                    ${
                        stop.is_next
                        ? "NEXT"
                        : escapeHtml(stop.status)
                    }
                </span>
            </div>
        `;
    }

    function renderSummary(payload) {
        const container = (
            document.getElementById(
                "driver-operational-map-summary"
            )
        );

        if (!container) return;

        const vehicle = payload.vehicle;
        const ride = payload.active_ride;

        if (!ride) {
            container.innerHTML = `
                <div class="driver-map-empty">
                    <strong>
                        No active ride
                    </strong>
                    <p class="text-muted">
                        Taxi #${vehicle.id}
                        is currently at
                        <strong>
                            ${
                                escapeHtml(
                                    vehicle.current_node?.name
                                    || "Unknown"
                                )
                            }
                        </strong>.
                    </p>
                </div>
            `;
            return;
        }

        const groupsHtml = (
            (ride.passenger_groups || [])
            .map(passengerGroupHtml)
            .join("")
        );

        const stopsHtml = (
            (ride.ordered_stops || [])
            .map(stopHtml)
            .join("")
        );

        const nextTarget = (
            ride.next_target
        );

        container.innerHTML = `
            <div class="driver-map-overview-grid">

                <div>
                    <span class="driver-map-label">
                        Active Ride
                    </span>
                    <strong>
                        #${ride.ride_id}
                        · ${escapeHtml(ride.ride_type)}
                    </strong>
                </div>

                <div>
                    <span class="driver-map-label">
                        Ride Status
                    </span>
                    <strong>
                        ${escapeHtml(
                            statusText(
                                ride.ride_status
                            )
                        )}
                    </strong>
                </div>

                <div>
                    <span class="driver-map-label">
                        Taxi Position
                    </span>
                    <strong>
                        ${escapeHtml(
                            vehicle.current_node?.name
                            || "Unknown"
                        )}
                    </strong>
                </div>

                <div>
                    <span class="driver-map-label">
                        Next Stop
                    </span>
                    <strong>
                        ${
                            nextTarget
                            ? `
                                ${escapeHtml(nextTarget.type)}
                                — ${escapeHtml(
                                    nextTarget.node?.name
                                )}
                            `
                            : "No pending stop"
                        }
                    </strong>
                </div>

                ${
                    ride.route_revision != null
                    ? `
                        <div>
                            <span class="driver-map-label">
                                Route Revision
                            </span>
                            <strong>
                                ${ride.route_revision}
                            </strong>
                        </div>
                    `
                    : ""
                }

                ${
                    ride.route_total_time_minutes != null
                    ? `
                        <div>
                            <span class="driver-map-label">
                                Estimated Route
                            </span>
                            <strong>
                                ${ride.route_total_time_minutes} min
                                ·
                                ${Number(
                                    ride.route_total_distance_km
                                ).toFixed(2)} km
                            </strong>
                        </div>
                    `
                    : ""
                }

            </div>

            <div class="driver-map-section">
                <h4>
                    Assigned Passenger Groups
                </h4>

                ${
                    groupsHtml
                    || `
                        <p class="text-muted">
                            No passenger group information.
                        </p>
                    `
                }
            </div>

            <div class="driver-map-section">
                <h4>
                    Ordered Stops
                </h4>

                ${
                    stopsHtml
                    || `
                        <p class="text-muted">
                            No route stops.
                        </p>
                    `
                }
            </div>
        `;
    }

    function renderDynamicState(payload) {
        if (!dynamicLayer) {
            dynamicLayer = L.layerGroup().addTo(
                map
            );
        }

        dynamicLayer.clearLayers();

        addTaxiMarker(
            payload.vehicle
        );

        const activeRide = (
            payload.active_ride
        );

        if (!activeRide) {
            return;
        }

        (activeRide.ordered_stops || [])
            .forEach(addStopMarker);

        drawRoutes(
            activeRide
        );
    }

    async function fetchState() {
        const response = await fetch(
            "/api/driver/rides/map/active/",
            {
                method: "GET",
                credentials: "same-origin",
            }
        );

        if (!response.ok) {
            let message = (
                "Could not load driver route map."
            );

            try {
                const data = (
                    await response.json()
                );

                message = (
                    data.detail
                    || message
                );
            } catch (_) {}

            throw new Error(message);
        }

        return response.json();
    }

    async function refresh() {
        if (
            loading
            || !map
        ) {
            return;
        }

        loading = true;

        try {
            const payload = (
                await fetchState()
            );

            renderSummary(
                payload
            );

            renderDynamicState(
                payload
            );

            const errorBox = (
                document.getElementById(
                    "driver-operational-map-error"
                )
            );

            if (errorBox) {
                errorBox.textContent = "";
            }

        } catch (error) {
            console.error(error);

            const errorBox = (
                document.getElementById(
                    "driver-operational-map-error"
                )
            );

            if (errorBox) {
                errorBox.textContent = (
                    error.message
                );
            }

        } finally {
            loading = false;
        }
    }

    async function init() {
        const mapElement = (
            document.getElementById(
                "driver-operational-map"
            )
        );

        if (!mapElement) return;

        if (
            typeof L === "undefined"
            || !core()
        ) {
            mapElement.innerHTML = `
                <div class="shared-error">
                    Map library was not loaded.
                </div>
            `;
            return;
        }

        try {
            network = (
                await core().loadNetwork()
            );

            const built = (
                core().createBaseMap(
                    "driver-operational-map",
                    network
                )
            );

            map = built.map;
            nodeById = built.nodeById;

            dynamicLayer = (
                L.layerGroup().addTo(
                    map
                )
            );

            await refresh();

            refreshTimer = setInterval(
                refresh,
                POLL_INTERVAL_MS
            );

            window.refreshDriverOperationalMap = (
                refresh
            );

        } catch (error) {
            console.error(error);

            mapElement.innerHTML = `
                <div class="shared-error">
                    ${escapeHtml(
                        error.message
                    )}
                </div>
            `;
        }
    }

    document.addEventListener(
        "DOMContentLoaded",
        init
    );

    window.addEventListener(
        "beforeunload",
        () => {
            if (refreshTimer) {
                clearInterval(
                    refreshTimer
                );
            }
        }
    );
})();
