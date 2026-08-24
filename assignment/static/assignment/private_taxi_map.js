(function () {
    "use strict";

    const state = {
        map: null,
        nodeById: {},
        routeLine: null,
        taxiMarkers: {},
    };

    function readJson(id, fallback) {
        const element = document.getElementById(id);

        if (!element) return fallback;

        try {
            return JSON.parse(
                element.textContent
            );
        } catch (error) {
            console.error(error);
            return fallback;
        }
    }

    function highlightRow(vehicleId) {
        document.querySelectorAll(
            ".private-option-row"
        ).forEach(row => {
            row.classList.remove(
                "taxi-option-selected"
            );
        });

        const row = document.getElementById(
            `private-option-vehicle-${vehicleId}`
        );

        if (row) {
            row.classList.add(
                "taxi-option-selected"
            );
        }
    }

    function showOption(vehicleId) {
        const options = readJson(
            "private-map-options-data",
            []
        );

        const option = options.find(
            item => (
                Number(item.vehicle_id)
                === Number(vehicleId)
            )
        );

        if (!option || !state.map) return;

        const path = (
            PassengerMapCore.mergePaths(
                option.pickup_path_node_ids,
                option.trip_path_node_ids
            )
        );

        state.routeLine = (
            PassengerMapCore.replacePath(
                state.routeLine,
                state.map,
                state.nodeById,
                path,
                {
                    weight: 8,
                    opacity: 0.9,
                    dashArray: "12, 7",
                }
            )
        );

        highlightRow(vehicleId);

        state.taxiMarkers[
            Number(vehicleId)
        ]?.openPopup();
    }

    function holdTaxi(vehicleId) {
        const form = document.querySelector(
            `form[data-private-vehicle-id="${vehicleId}"]`
        );

        if (form) {
            form.submit();
        }
    }

    async function init() {
        const mapElement = document.getElementById(
            "private-taxi-map"
        );

        if (!mapElement) return;

        try {
            const network = await (
                PassengerMapCore.loadNetwork()
            );

            const base = (
                PassengerMapCore.createBaseMap(
                    "private-taxi-map",
                    network
                )
            );

            state.map = base.map;
            state.nodeById = base.nodeById;

            const pickupNode = state.nodeById[
                Number(
                    mapElement.dataset
                        .pickupNodeId
                )
            ];

            const destinationNode = state.nodeById[
                Number(
                    mapElement.dataset
                        .destinationNodeId
                )
            ];

            if (pickupNode) {
                PassengerMapCore
                    .addPickupMarker(
                        state.map,
                        pickupNode
                    );
            }

            if (destinationNode) {
                PassengerMapCore
                    .addDestinationMarker(
                        state.map,
                        destinationNode
                    );
            }

            const options = readJson(
                "private-map-options-data",
                []
            );

            const heldVehicle = readJson(
                "private-held-vehicle-data",
                null
            );

            options.forEach(option => {
                const node = state.nodeById[
                    Number(
                        option.current_node_id
                    )
                ];

                if (!node) return;

                const popup = `
                    <strong>
                        #${PassengerMapCore.escapeHtml(
                            option.rank
                        )}
                        Taxi ${PassengerMapCore.escapeHtml(
                            option.vehicle_id
                        )}
                    </strong>
                    <br>
                    Driver:
                    ${PassengerMapCore.escapeHtml(
                        option.driver_username
                    )}
                    <br>
                    Current node:
                    ${PassengerMapCore.escapeHtml(
                        option.current_node_name
                    )}
                    <br>
                    Capacity:
                    ${PassengerMapCore.escapeHtml(
                        option.capacity
                    )}
                    <br>
                    Pickup ETA:
                    ${PassengerMapCore.escapeHtml(
                        option.pickup_eta_minutes
                    )} min
                    <br>
                    Pickup distance:
                    ${Number(
                        option.pickup_distance_km
                    ).toFixed(2)} km
                    <br>
                    Trip ETA:
                    ${PassengerMapCore.escapeHtml(
                        option.trip_eta_minutes
                    )} min
                    <br>
                    Price:
                    €${Number(
                        option.estimated_price
                    ).toFixed(2)}
                    <br><br>
                    <button
                        type="button"
                        class="map-popup-button"
                        onclick="PrivateTaxiMap.showOption(${Number(
                            option.vehicle_id
                        )})"
                    >
                        Show route
                    </button>
                    <button
                        type="button"
                        class="map-popup-button map-popup-primary"
                        onclick="PrivateTaxiMap.holdTaxi(${Number(
                            option.vehicle_id
                        )})"
                    >
                        Hold taxi
                    </button>
                `;

                const marker = (
                    PassengerMapCore
                    .addTaxiMarker(
                        state.map,
                        node,
                        `T${option.rank}`,
                        popup
                    )
                );

                marker.on(
                    "click",
                    () => {
                        showOption(
                            option.vehicle_id
                        );
                    }
                );

                state.taxiMarkers[
                    Number(option.vehicle_id)
                ] = marker;
            });

            if (
                heldVehicle
                && heldVehicle.current_node_id
            ) {
                const heldNode = state.nodeById[
                    Number(
                        heldVehicle.current_node_id
                    )
                ];

                if (heldNode) {
                    PassengerMapCore
                        .addTaxiMarker(
                            state.map,
                            heldNode,
                            "H",
                            `
                                <strong>
                                    Held Taxi
                                    #${PassengerMapCore.escapeHtml(
                                        heldVehicle.vehicle_id
                                    )}
                                </strong>
                                <br>
                                Current node:
                                ${PassengerMapCore.escapeHtml(
                                    heldVehicle.current_node_name
                                )}
                            `
                        );
                }
            }

            if (options.length > 0) {
                showOption(
                    options[0].vehicle_id
                );
            }
        } catch (error) {
            console.error(error);

            mapElement.innerHTML = `
                <p class="shared-error">
                    ${PassengerMapCore.escapeHtml(
                        error.message
                    )}
                </p>
            `;
        }
    }

    window.PrivateTaxiMap = {
        init,
        showOption,
        holdTaxi,
    };

    document.addEventListener(
        "DOMContentLoaded",
        init
    );
})();
