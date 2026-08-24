(function () {
    "use strict";

    const state = {
        mode: "pickup",
        map: null,
        nodeById: {},
        pickupMarker: null,
        destinationMarker: null,
        previewLine: null,
    };

    function el(id) {
        return document.getElementById(id);
    }

    function setMode(mode) {
        state.mode = mode;

        const pickupButton = el("select-pickup-mode");
        const destinationButton = el("select-destination-mode");

        if (pickupButton) {
            pickupButton.classList.toggle(
                "map-selection-mode-active",
                mode === "pickup"
            );
        }

        if (destinationButton) {
            destinationButton.classList.toggle(
                "map-selection-mode-active",
                mode === "destination"
            );
        }

        const hint = el("map-selection-hint");

        if (hint) {
            hint.textContent = (
                mode === "pickup"
                    ? "Click a road node to choose your pickup."
                    : "Click a road node to choose your destination."
            );
        }
    }

    function updateSelectedLabel(type, node) {
        const target = el(
            type === "pickup"
                ? "selected-pickup-label"
                : "selected-destination-label"
        );

        if (!target) return;

        target.textContent = node
            ? `${node.name} (#${node.id})`
            : "Not selected";
    }

    function removeMarker(marker) {
        if (marker && state.map) {
            state.map.removeLayer(marker);
        }
    }

    async function refreshRoutePreview() {
        const pickupInput = el("id_pickup_node");
        const destinationInput = el("id_destination_node");
        const summary = el("route-preview-summary");

        if (
            !pickupInput
            || !destinationInput
            || !pickupInput.value
            || !destinationInput.value
        ) {
            if (state.previewLine && state.map) {
                state.map.removeLayer(state.previewLine);
                state.previewLine = null;
            }

            if (summary) {
                summary.textContent = (
                    "Select pickup and destination to preview the route."
                );
            }
            return;
        }

        try {
            const response = await fetch(
                `/api/road-network/route/?start=${encodeURIComponent(
                    pickupInput.value
                )}&end=${encodeURIComponent(
                    destinationInput.value
                )}`,
                {credentials: "same-origin"}
            );

            const data = await response.json();

            if (!response.ok) {
                throw new Error(
                    data.detail || "Route preview failed."
                );
            }

            const pathIds = (data.path || [])
                .map(node => node.id);

            state.previewLine = (
                PassengerMapCore.replacePath(
                    state.previewLine,
                    state.map,
                    state.nodeById,
                    pathIds,
                    {
                        weight: 7,
                        opacity: 0.8,
                        dashArray: "12, 7",
                    }
                )
            );

            if (summary) {
                summary.textContent = (
                    `${Number(
                        data.total_distance_km
                    ).toFixed(2)} km • `
                    + `${data.total_time_minutes} min`
                );
            }
        } catch (error) {
            console.error(error);

            if (summary) {
                summary.textContent = (
                    error.message
                    || "Could not preview this route."
                );
            }
        }
    }

    function chooseNode(node) {
        const pickupInput = el("id_pickup_node");
        const destinationInput = el("id_destination_node");

        if (!pickupInput || !destinationInput) {
            return;
        }

        if (state.mode === "pickup") {
            if (
                destinationInput.value
                && Number(destinationInput.value)
                    === Number(node.id)
            ) {
                alert(
                    "Pickup and destination must be different."
                );
                return;
            }

            pickupInput.value = node.id;

            removeMarker(state.pickupMarker);
            state.pickupMarker = (
                PassengerMapCore.addPickupMarker(
                    state.map,
                    node
                )
            );

            updateSelectedLabel("pickup", node);
            setMode("destination");
        } else {
            if (
                pickupInput.value
                && Number(pickupInput.value)
                    === Number(node.id)
            ) {
                alert(
                    "Pickup and destination must be different."
                );
                return;
            }

            destinationInput.value = node.id;

            removeMarker(state.destinationMarker);
            state.destinationMarker = (
                PassengerMapCore.addDestinationMarker(
                    state.map,
                    node
                )
            );

            updateSelectedLabel(
                "destination",
                node
            );
        }

        refreshRoutePreview();
    }

    function clearSelection() {
        const pickupInput = el("id_pickup_node");
        const destinationInput = el("id_destination_node");

        if (pickupInput) pickupInput.value = "";
        if (destinationInput) destinationInput.value = "";

        removeMarker(state.pickupMarker);
        removeMarker(state.destinationMarker);

        state.pickupMarker = null;
        state.destinationMarker = null;

        if (state.previewLine && state.map) {
            state.map.removeLayer(state.previewLine);
            state.previewLine = null;
        }

        updateSelectedLabel("pickup", null);
        updateSelectedLabel("destination", null);

        setMode("pickup");
        refreshRoutePreview();
    }

    function restoreExistingSelections() {
        const pickupInput = el("id_pickup_node");
        const destinationInput = el("id_destination_node");

        if (
            pickupInput
            && pickupInput.value
            && state.nodeById[
                Number(pickupInput.value)
            ]
        ) {
            const node = state.nodeById[
                Number(pickupInput.value)
            ];

            state.pickupMarker = (
                PassengerMapCore.addPickupMarker(
                    state.map,
                    node
                )
            );

            updateSelectedLabel("pickup", node);
        }

        if (
            destinationInput
            && destinationInput.value
            && state.nodeById[
                Number(destinationInput.value)
            ]
        ) {
            const node = state.nodeById[
                Number(destinationInput.value)
            ];

            state.destinationMarker = (
                PassengerMapCore.addDestinationMarker(
                    state.map,
                    node
                )
            );

            updateSelectedLabel(
                "destination",
                node
            );
        }

        refreshRoutePreview();
    }

    async function init() {
        const mapElement = el("passenger-node-map");

        if (!mapElement) return;

        try {
            const network = await (
                PassengerMapCore.loadNetwork()
            );

            const base = (
                PassengerMapCore.createBaseMap(
                    "passenger-node-map",
                    network,
                    {
                        onNodeClick: chooseNode,
                    }
                )
            );

            state.map = base.map;
            state.nodeById = base.nodeById;

            el("select-pickup-mode")
                ?.addEventListener(
                    "click",
                    () => setMode("pickup")
                );

            el("select-destination-mode")
                ?.addEventListener(
                    "click",
                    () => setMode("destination")
                );

            el("clear-map-selection")
                ?.addEventListener(
                    "click",
                    clearSelection
                );

            const form = el("ride-request-form");

            if (form) {
                form.addEventListener(
                    "submit",
                    event => {
                        const pickup = el("id_pickup_node");
                        const destination = el(
                            "id_destination_node"
                        );

                        if (
                            !pickup?.value
                            || !destination?.value
                        ) {
                            event.preventDefault();
                            alert(
                                "Please select both pickup and destination on the map."
                            );
                        }
                    }
                );
            }

            setMode("pickup");
            restoreExistingSelections();
        } catch (error) {
            console.error(error);

            mapElement.innerHTML = (
                `<p class="shared-error">`
                + `${PassengerMapCore.escapeHtml(
                    error.message
                )}</p>`
            );
        }
    }

    window.PassengerNodeMap = {
        init,
        setMode,
        clearSelection,
    };

    document.addEventListener(
        "DOMContentLoaded",
        init
    );
})();
