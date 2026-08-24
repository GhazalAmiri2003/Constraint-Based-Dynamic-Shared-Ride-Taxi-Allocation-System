// =========================================================
// Shared Ride - Passenger UI + Taxi Map
// =========================================================

const sharedRideMapStates = {};

function getCsrfToken() {
    const cookieValue = document.cookie
        .split("; ")
        .find(row => row.startsWith("csrftoken="));

    if (!cookieValue) return "";

    return decodeURIComponent(
        cookieValue.split("=")[1]
    );
}

async function getApiError(response) {
    try {
        const data = await response.json();
        return data.detail || "Something went wrong.";
    } catch {
        return "Something went wrong.";
    }
}

async function findSharedTaxis(
    rideRequestId
) {
    const container = document.getElementById(
        `shared-options-${rideRequestId}`
    );

    if (!container) return;

    container.innerHTML = `
        <p>Searching feasible shared taxis...</p>
    `;

    try {
        const response = await fetch(
            `/api/assignment/ride-requests/${rideRequestId}/shared-options/`,
            {
                method: "GET",
                credentials: "same-origin",
            }
        );

        if (!response.ok) {
            const message = await getApiError(
                response
            );

            container.innerHTML = `
                <p class="shared-error">
                    ${PassengerMapCore.escapeHtml(
                        message
                    )}
                </p>
            `;
            return;
        }

        const data = await response.json();

        if (
            !data.options
            || data.options.length === 0
        ) {
            container.innerHTML = `
                <p>
                    No feasible shared taxi is
                    available right now.
                </p>
            `;
            return;
        }

        await renderSharedOptions(
            rideRequestId,
            data.options
        );

    } catch (error) {
        console.error(error);

        container.innerHTML = `
            <p class="shared-error">
                Could not load shared taxi options.
            </p>
        `;
    }
}

function buildSharedRouteHtml(option) {
    return (
        (option.proposed_route || [])
        .map(stop => `
            <li>
                <strong>
                    ${PassengerMapCore.escapeHtml(
                        stop.sequence_number
                    )}.
                </strong>

                ${PassengerMapCore.escapeHtml(
                    stop.stop_type
                )}
                —
                ${PassengerMapCore.escapeHtml(
                    stop.node_name
                )}

                <small>
                    ETA:
                    ${PassengerMapCore.escapeHtml(
                        stop.estimated_arrival_minutes
                    )}
                    min
                </small>
            </li>
        `)
        .join("")
    );
}

function buildSharedOptionCard(
    rideRequestId,
    option
) {
    return `
        <div
            class="shared-option-card"
            id="shared-option-${rideRequestId}-${option.vehicle_id}"
            onclick="
                highlightSharedTaxi(
                    ${rideRequestId},
                    ${option.vehicle_id}
                )
            "
        >

            <div class="shared-option-header">

                <h4>
                    #${PassengerMapCore.escapeHtml(
                        option.rank
                    )}
                    Shared Taxi
                </h4>

                <span>
                    Vehicle
                    ${PassengerMapCore.escapeHtml(
                        option.vehicle_id
                    )}
                </span>

            </div>

            <div class="shared-option-grid">

                <div>
                    <strong>Current node</strong>
                    <span>
                        ${PassengerMapCore.escapeHtml(
                            option.current_node?.name
                            || "-"
                        )}
                    </span>
                </div>

                <div>
                    <strong>Pickup ETA</strong>
                    <span>
                        ${PassengerMapCore.escapeHtml(
                            option.pickup_eta_minutes
                        )} min
                    </span>
                </div>

                <div>
                    <strong>Trip duration</strong>
                    <span>
                        ${PassengerMapCore.escapeHtml(
                            option.estimated_trip_duration_minutes
                        )} min
                    </span>
                </div>

                <div>
                    <strong>Shared delay</strong>
                    <span>
                        ${PassengerMapCore.escapeHtml(
                            option.expected_shared_delay_minutes
                        )} min
                    </span>
                </div>

                <div>
                    <strong>Available seats</strong>
                    <span>
                        ${PassengerMapCore.escapeHtml(
                            option.available_seats_at_pickup
                        )}
                    </span>
                </div>

                <div>
                    <strong>Price</strong>
                    <span>
                        €${Number(
                            option.estimated_price
                        ).toFixed(2)}
                    </span>
                </div>

                <div>
                    <strong>Route extension</strong>
                    <span>
                        ${Number(
                            option.route_extension_km
                        ).toFixed(2)} km
                    </span>
                </div>

            </div>

            <details
                class="shared-route-details"
                onclick="event.stopPropagation();"
            >
                <summary>
                    Proposed route
                </summary>

                <ol>
                    ${buildSharedRouteHtml(option)}
                </ol>
            </details>

            <button
                type="button"
                class="btn btn-primary"
                onclick="
                    event.stopPropagation();
                    holdSharedTaxi(
                        ${rideRequestId},
                        ${option.vehicle_id}
                    )
                "
            >
                Hold this taxi
            </button>

        </div>
    `;
}

async function renderSharedOptions(
    rideRequestId,
    options
) {
    const container = document.getElementById(
        `shared-options-${rideRequestId}`
    );

    if (!container) return;

    const cards = options.map(
        option => buildSharedOptionCard(
            rideRequestId,
            option
        )
    );

    container.innerHTML = `
        <div class="shared-taxi-map-layout">

            <div>
                <h4>
                    Feasible Shared Taxis on Map
                </h4>

                <p class="text-muted">
                    Click a taxi marker or a card to
                    inspect its position and proposed route.
                </p>

                <div
                    id="shared-taxi-map-${rideRequestId}"
                    class="passenger-map taxi-options-map"
                >
                </div>
            </div>

            <div class="shared-map-options-list">
                ${cards.join("")}
            </div>

        </div>
    `;

    await renderSharedTaxiMap(
        rideRequestId,
        options
    );
}

async function renderSharedTaxiMap(
    rideRequestId,
    options
) {
    const container = document.getElementById(
        `shared-options-${rideRequestId}`
    );

    if (!container) return;

    const pickupNodeId = Number(
        container.dataset.pickupNodeId
    );

    const destinationNodeId = Number(
        container.dataset.destinationNodeId
    );

    const network = await (
        PassengerMapCore.loadNetwork()
    );

    const base = (
        PassengerMapCore.createBaseMap(
            `shared-taxi-map-${rideRequestId}`,
            network
        )
    );

    const mapState = {
        map: base.map,
        nodeById: base.nodeById,
        routeLine: null,
        taxiMarkers: {},
        optionsByVehicle: {},
    };

    sharedRideMapStates[
        Number(rideRequestId)
    ] = mapState;

    const pickupNode = mapState.nodeById[
        pickupNodeId
    ];

    const destinationNode = mapState.nodeById[
        destinationNodeId
    ];

    if (pickupNode) {
        PassengerMapCore.addPickupMarker(
            mapState.map,
            pickupNode
        );
    }

    if (destinationNode) {
        PassengerMapCore.addDestinationMarker(
            mapState.map,
            destinationNode
        );
    }

    options.forEach(option => {
        mapState.optionsByVehicle[
            Number(option.vehicle_id)
        ] = option;

        const taxiNode = mapState.nodeById[
            Number(option.current_node?.id)
        ];

        if (!taxiNode) return;

        const popup = `
            <strong>
                Shared Taxi
                #${PassengerMapCore.escapeHtml(
                    option.vehicle_id
                )}
            </strong>
            <br>
            Rank:
            #${PassengerMapCore.escapeHtml(
                option.rank
            )}
            <br>
            Driver:
            ${PassengerMapCore.escapeHtml(
                option.driver_username
            )}
            <br>
            Current node:
            ${PassengerMapCore.escapeHtml(
                option.current_node?.name
                || "-"
            )}
            <br>
            Pickup ETA:
            ${PassengerMapCore.escapeHtml(
                option.pickup_eta_minutes
            )} min
            <br>
            Shared delay:
            ${PassengerMapCore.escapeHtml(
                option.expected_shared_delay_minutes
            )} min
            <br>
            Seats at pickup:
            ${PassengerMapCore.escapeHtml(
                option.available_seats_at_pickup
            )}
            <br>
            Price:
            €${Number(
                option.estimated_price
            ).toFixed(2)}
            <br><br>
            <button
                type="button"
                class="map-popup-button"
                onclick="
                    highlightSharedTaxi(
                        ${rideRequestId},
                        ${option.vehicle_id}
                    )
                "
            >
                Show proposed route
            </button>
            <button
                type="button"
                class="map-popup-button map-popup-primary"
                onclick="
                    holdSharedTaxi(
                        ${rideRequestId},
                        ${option.vehicle_id}
                    )
                "
            >
                Hold taxi
            </button>
        `;

        const marker = (
            PassengerMapCore.addTaxiMarker(
                mapState.map,
                taxiNode,
                `T${option.rank}`,
                popup
            )
        );

        marker.on(
            "click",
            () => {
                highlightSharedTaxi(
                    rideRequestId,
                    option.vehicle_id
                );
            }
        );

        mapState.taxiMarkers[
            Number(option.vehicle_id)
        ] = marker;
    });

    if (options.length > 0) {
        await highlightSharedTaxi(
            rideRequestId,
            options[0].vehicle_id
        );
    }
}

async function highlightSharedTaxi(
    rideRequestId,
    vehicleId
) {
    const mapState = (
        sharedRideMapStates[
            Number(rideRequestId)
        ]
    );

    if (!mapState) return;

    const option = (
        mapState.optionsByVehicle[
            Number(vehicleId)
        ]
    );

    if (!option) return;

    document.querySelectorAll(
        `#shared-options-${rideRequestId} .shared-option-card`
    ).forEach(card => {
        card.classList.remove(
            "taxi-option-selected"
        );
    });

    const selectedCard = document.getElementById(
        `shared-option-${rideRequestId}-${vehicleId}`
    );

    if (selectedCard) {
        selectedCard.classList.add(
            "taxi-option-selected"
        );
    }

    // Build the real simulated graph route between
    // current taxi position and every proposed RouteStop.
    const orderedNodeIds = [];

    if (option.current_node?.id) {
        orderedNodeIds.push(
            Number(option.current_node.id)
        );
    }

    (option.proposed_route || [])
        .forEach(stop => {
            const nodeId = Number(
                stop.node_id
            );

            if (
                orderedNodeIds.length === 0
                || orderedNodeIds[
                    orderedNodeIds.length - 1
                ] !== nodeId
            ) {
                orderedNodeIds.push(nodeId);
            }
        });

    let fullPath = [];

    try {
        for (
            let index = 0;
            index < orderedNodeIds.length - 1;
            index += 1
        ) {
            const startId = orderedNodeIds[index];
            const endId = orderedNodeIds[index + 1];

            const response = await fetch(
                `/api/road-network/route/?start=${startId}&end=${endId}`,
                {
                    credentials: "same-origin",
                }
            );

            const data = await response.json();

            if (!response.ok) {
                throw new Error(
                    data.detail
                    || "Could not preview shared route."
                );
            }

            fullPath = (
                PassengerMapCore.mergePaths(
                    fullPath,
                    (data.path || []).map(
                        node => node.id
                    )
                )
            );
        }
    } catch (error) {
        console.error(error);

        // Visual fallback: connect ordered stops directly.
        fullPath = orderedNodeIds;
    }

    mapState.routeLine = (
        PassengerMapCore.replacePath(
            mapState.routeLine,
            mapState.map,
            mapState.nodeById,
            fullPath,
            {
                weight: 8,
                opacity: 0.9,
                dashArray: "12, 7",
            }
        )
    );

    mapState.taxiMarkers[
        Number(vehicleId)
    ]?.openPopup();
}

async function holdSharedTaxi(
    rideRequestId,
    vehicleId
) {
    const container = document.getElementById(
        `shared-options-${rideRequestId}`
    );

    try {
        const response = await fetch(
            `/api/assignment/ride-requests/${rideRequestId}/shared-hold/`,
            {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type":
                        "application/json",
                    "X-CSRFToken":
                        getCsrfToken(),
                },
                body: JSON.stringify({
                    vehicle_id: vehicleId,
                }),
            }
        );

        if (!response.ok) {
            const message = await getApiError(
                response
            );

            alert(message);

            await findSharedTaxis(
                rideRequestId
            );
            return;
        }

        const hold = await response.json();

        renderActiveSharedHold(
            rideRequestId,
            hold
        );

    } catch (error) {
        console.error(error);
        alert(
            "Could not hold the selected taxi."
        );
    }
}

function renderActiveSharedHold(
    rideRequestId,
    hold
) {
    const container = document.getElementById(
        `shared-options-${rideRequestId}`
    );

    if (!container) return;

    container.innerHTML = `
        <div
            class="shared-hold-card"
            id="shared-hold-${hold.hold_id}"
        >

            <h4>
                Taxi temporarily held
            </h4>

            <p>
                Vehicle:
                <strong>
                    ${PassengerMapCore.escapeHtml(
                        hold.vehicle_id
                    )}
                </strong>
            </p>

            <p>
                Time remaining:
                <strong
                    id="shared-hold-countdown-${hold.hold_id}"
                >
                    --
                </strong>
            </p>

            <div class="shared-hold-actions">

                <button
                    type="button"
                    class="btn btn-success"
                    onclick="
                        confirmSharedHold(
                            ${hold.hold_id}
                        )
                    "
                >
                    Confirm taxi
                </button>

                <button
                    type="button"
                    class="btn btn-secondary"
                    onclick="
                        releaseSharedHold(
                            ${rideRequestId},
                            ${hold.hold_id}
                        )
                    "
                >
                    Release
                </button>

            </div>

        </div>
    `;

    startSharedHoldCountdown(
        rideRequestId,
        hold.hold_id,
        hold.expires_at
    );
}

function startSharedHoldCountdown(
    rideRequestId,
    holdId,
    expiresAt
) {
    const countdownElement = (
        document.getElementById(
            `shared-hold-countdown-${holdId}`
        )
    );

    if (!countdownElement) return;

    const expiration = new Date(
        expiresAt
    ).getTime();

    const timer = setInterval(
        () => {
            const remainingMs = (
                expiration - Date.now()
            );

            if (remainingMs <= 0) {
                clearInterval(timer);

                countdownElement.textContent =
                    "Expired";

                setTimeout(
                    () => {
                        findSharedTaxis(
                            rideRequestId
                        );
                    },
                    1000
                );
                return;
            }

            const seconds = Math.ceil(
                remainingMs / 1000
            );

            const minutesPart = Math.floor(
                seconds / 60
            );

            const secondsPart = seconds % 60;

            countdownElement.textContent = (
                `${minutesPart}:`
                + `${String(
                    secondsPart
                ).padStart(2, "0")}`
            );
        },
        1000
    );
}

async function confirmSharedHold(holdId) {
    try {
        const response = await fetch(
            `/api/assignment/shared-holds/${holdId}/confirm/`,
            {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type":
                        "application/json",
                    "X-CSRFToken":
                        getCsrfToken(),
                },
                body: JSON.stringify({}),
            }
        );

        if (!response.ok) {
            const message = await getApiError(
                response
            );

            alert(message);
            window.location.reload();
            return;
        }

        const data = await response.json();

        alert(
            `Shared taxi confirmed. Ride #${data.ride_id}`
        );

        window.location.reload();

    } catch (error) {
        console.error(error);
        alert(
            "Could not confirm the shared taxi."
        );
    }
}

async function releaseSharedHold(
    rideRequestId,
    holdId
) {
    try {
        const response = await fetch(
            `/api/assignment/shared-holds/${holdId}/release/`,
            {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type":
                        "application/json",
                    "X-CSRFToken":
                        getCsrfToken(),
                },
                body: JSON.stringify({}),
            }
        );

        if (!response.ok) {
            const message = await getApiError(
                response
            );

            alert(message);
            return;
        }

        await findSharedTaxis(
            rideRequestId
        );

    } catch (error) {
        console.error(error);
        alert(
            "Could not release the taxi."
        );
    }
}
