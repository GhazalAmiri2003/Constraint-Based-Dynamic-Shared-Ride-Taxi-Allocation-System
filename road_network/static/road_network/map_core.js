(function () {
    "use strict";

    let networkPromise = null;

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    async function loadNetwork() {
        if (!networkPromise) {
            networkPromise = fetch(
                "/api/road-network/passenger-network/",
                {
                    method: "GET",
                    credentials: "same-origin",
                }
            ).then(async response => {
                if (!response.ok) {
                    let message = "Could not load the road network.";
                    try {
                        const data = await response.json();
                        message = data.detail || message;
                    } catch (_) {}
                    throw new Error(message);
                }
                return response.json();
            });
        }
        return networkPromise;
    }

    function buildNodeIndex(network) {
        const nodeById = {};
        (network.nodes || []).forEach(node => {
            nodeById[Number(node.id)] = node;
        });
        return nodeById;
    }

    function nodePosition(node) {
        return [Number(node.y), Number(node.x)];
    }

    function fitNetwork(map, network) {
        if (!network.nodes || network.nodes.length === 0) {
            map.setView([0, 0], 0);
            return;
        }

        const bounds = L.latLngBounds(
            network.nodes.map(nodePosition)
        );

        map.fitBounds(
            bounds.pad(0.15),
            {padding: [24, 24]}
        );
    }

    function createBaseMap(elementId, network, options = {}) {
        const element = document.getElementById(elementId);
        if (!element) {
            throw new Error(
                `Map container "${elementId}" was not found.`
            );
        }

        const map = L.map(
            elementId,
            {
                crs: L.CRS.Simple,
                minZoom: -2,
                maxZoom: 10,
                zoomSnap: 0.25,
                attributionControl: false,
            }
        );

        const nodeById = buildNodeIndex(network);

        (network.edges || []).forEach(edge => {
            const fromNode = nodeById[Number(edge.from_node_id)];
            const toNode = nodeById[Number(edge.to_node_id)];
            if (!fromNode || !toNode) return;

            L.polyline(
                [nodePosition(fromNode), nodePosition(toNode)],
                {weight: 3, opacity: 0.55}
            )
            .addTo(map)
            .bindTooltip(
                `${escapeHtml(fromNode.name)} → ${escapeHtml(toNode.name)}`
            );
        });

        const nodeLayers = {};

        (network.nodes || []).forEach(node => {
            const layer = L.circleMarker(
                nodePosition(node),
                {
                    radius: 7,
                    weight: 2,
                    fillOpacity: 0.9,
                }
            )
            .addTo(map)
            .bindTooltip(
                escapeHtml(node.name),
                {direction: "top"}
            );

            if (typeof options.onNodeClick === "function") {
                layer.on("click", () => {
                    options.onNodeClick(node, layer, map);
                });
            }

            nodeLayers[Number(node.id)] = layer;
        });

        fitNetwork(map, network);

        return {map, nodeById, nodeLayers};
    }

    function createDivIcon(className, text, size = 34) {
        return L.divIcon({
            className: "",
            html: `
                <div class="${className}">
                    ${escapeHtml(text)}
                </div>
            `,
            iconSize: [size, size],
            iconAnchor: [size / 2, size / 2],
        });
    }

    function addPickupMarker(map, node) {
        return L.marker(
            nodePosition(node),
            {
                icon: createDivIcon(
                    "map-pickup-marker",
                    "P",
                    32
                ),
                zIndexOffset: 500,
            }
        )
        .addTo(map)
        .bindPopup(
            `<strong>Pickup</strong><br>${escapeHtml(node.name)}`
        );
    }

    function addDestinationMarker(map, node) {
        return L.marker(
            nodePosition(node),
            {
                icon: createDivIcon(
                    "map-destination-marker",
                    "D",
                    32
                ),
                zIndexOffset: 500,
            }
        )
        .addTo(map)
        .bindPopup(
            `<strong>Destination</strong><br>${escapeHtml(node.name)}`
        );
    }

    function addTaxiMarker(map, node, label, popupHtml) {
        const marker = L.marker(
            nodePosition(node),
            {
                icon: createDivIcon(
                    "map-taxi-marker",
                    label || "T",
                    38
                ),
                zIndexOffset: 700,
            }
        ).addTo(map);

        if (popupHtml) marker.bindPopup(popupHtml);
        return marker;
    }

    function pathPositions(pathNodeIds, nodeById) {
        return (pathNodeIds || [])
            .map(nodeId => nodeById[Number(nodeId)])
            .filter(Boolean)
            .map(nodePosition);
    }

    function drawPath(map, nodeById, pathNodeIds, options = {}) {
        const positions = pathPositions(
            pathNodeIds,
            nodeById
        );

        if (positions.length < 2) return null;

        return L.polyline(
            positions,
            {
                weight: options.weight || 7,
                opacity: options.opacity || 0.8,
                dashArray: options.dashArray || null,
            }
        ).addTo(map);
    }

    function replacePath(
        currentLayer,
        map,
        nodeById,
        pathNodeIds,
        options = {}
    ) {
        if (currentLayer) {
            map.removeLayer(currentLayer);
        }

        return drawPath(
            map,
            nodeById,
            pathNodeIds,
            options
        );
    }

    function mergePaths(...paths) {
        const merged = [];

        paths.forEach(path => {
            (path || []).forEach(nodeId => {
                const numericId = Number(nodeId);
                if (
                    merged.length === 0
                    || merged[merged.length - 1] !== numericId
                ) {
                    merged.push(numericId);
                }
            });
        });

        return merged;
    }

    window.PassengerMapCore = {
        escapeHtml,
        loadNetwork,
        buildNodeIndex,
        nodePosition,
        createBaseMap,
        addPickupMarker,
        addDestinationMarker,
        addTaxiMarker,
        drawPath,
        replacePath,
        mergePaths,
        fitNetwork,
    };
})();
