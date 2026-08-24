// =========================================================
// Shared Ride - Driver UI
// =========================================================

function getDriverCsrfToken() {
    const cookieValue = document.cookie
        .split("; ")
        .find(row => row.startsWith("csrftoken="));

    if (!cookieValue) {
        return "";
    }

    return decodeURIComponent(
        cookieValue.split("=")[1]
    );
}




// =========================================================
// Refresh Driver Operational Map
// =========================================================

async function refreshDriverMapIfAvailable() {

    if (
        typeof window.refreshDriverOperationalMap
        === "function"
    ) {

        await (
            window
            .refreshDriverOperationalMap()
        );
    }
}


// =========================================================
// Generic API Error
// =========================================================

async function getDriverApiError(response) {
    try {
        const data = await response.json();

        return (
            data.detail
            || "Something went wrong."
        );
    } catch {
        return "Something went wrong.";
    }
}


// =========================================================
// Load Active Shared Ride
// =========================================================

async function loadActiveSharedRide() {

    const container = document.getElementById(
        "active-shared-ride-container"
    );

    if (!container) {
        return;
    }


    container.innerHTML = `
        <p class="text-muted">
            Loading shared ride...
        </p>
    `;


    try {

        const response = await fetch(
            "/api/assignment/driver/shared-ride/active/",
            {
                method: "GET",
                credentials: "same-origin",
            }
        );


        if (!response.ok) {

            const message = await getDriverApiError(
                response
            );

            container.innerHTML = `
                <p class="shared-error">
                    ${message}
                </p>
            `;

            return;
        }


        const data = await response.json();

        const sharedRide = (
            data.active_shared_ride
        );


        // Driver currently has no active Shared Ride.
        if (!sharedRide) {

            container.innerHTML = `
                <p class="text-muted">
                    No active shared ride.
                </p>
            `;

            return;
        }


        renderActiveSharedRide(
            sharedRide
        );

    } catch (error) {

        console.error(error);

        container.innerHTML = `
            <p class="shared-error">
                Could not load the active shared ride.
            </p>
        `;
    }
}


// =========================================================
// Render Shared Ride
// =========================================================

function renderActiveSharedRide(
    sharedRide
) {

    const container = document.getElementById(
        "active-shared-ride-container"
    );


    const currentNode = (
        sharedRide.current_node
        ? sharedRide.current_node.name
        : "Unknown"
    );


    const stopsHtml = (
        sharedRide.stops
        .map(
            stop => {

                let statusClass = (
                    "shared-stop-pending"
                );


                if (
                    stop.status === "COMPLETED"
                ) {
                    statusClass = (
                        "shared-stop-completed"
                    );
                }


                if (
                    stop.status === "CANCELLED"
                ) {
                    statusClass = (
                        "shared-stop-cancelled"
                    );
                }


                return `
                    <div
                        class="shared-driver-stop ${statusClass}"
                    >

                        <div class="shared-driver-stop-number">
                            ${stop.sequence_number}
                        </div>


                        <div class="shared-driver-stop-content">

                            <strong>
                                ${stop.stop_type}
                            </strong>

                            <span>
                                ${stop.node.name}
                            </span>

                            <small>
                                Passenger group/request:
                                #${stop.ride_request_id}
                            </small>

                            <small>
                                Passengers:
                                ${stop.passenger_count}
                            </small>

                            <small>
                                ETA:
                                ${
                                    stop.estimated_arrival_minutes
                                    ?? "-"
                                }
                                min
                            </small>

                        </div>


                        <div>
                            <span class="status">
                                ${stop.status}
                            </span>
                        </div>

                    </div>
                `;
            }
        )
        .join("")
    );


    // Ride cannot move until accepted.
    const canMove = (
        sharedRide.ride_status === "ACCEPTED"
        ||
        sharedRide.ride_status === "IN_PROGRESS"
    );


    const movementSection = canMove
        ? `
            <button
                type="button"
                class="btn btn-primary"
                id="shared-move-next-button"
                onclick="moveSharedTaxiNext()"
            >
                Move Next
            </button>
        `
        : `
            <p class="text-muted">
                Accept this ride first to start movement.
            </p>
        `;


    container.innerHTML = `

        <div class="shared-driver-card">

            <div class="shared-driver-header">

                <div>

                    <h3>
                        Shared Ride #${sharedRide.ride_id}
                    </h3>

                    <p class="text-muted">
                        Route revision:
                        ${sharedRide.route.revision}
                    </p>

                </div>


                <span class="status">
                    ${sharedRide.ride_status}
                </span>

            </div>


            <div class="shared-driver-summary">

                <div>
                    <strong>
                        Current Node
                    </strong>

                    <span>
                        ${currentNode}
                    </span>
                </div>


                <div>
                    <strong>
                        Route Time
                    </strong>

                    <span>
                        ${sharedRide.route.total_estimated_time_minutes}
                        min
                    </span>
                </div>


                <div>
                    <strong>
                        Route Distance
                    </strong>

                    <span>
                        ${Number(
                            sharedRide.route.total_estimated_distance_km
                        ).toFixed(2)}
                        km
                    </span>
                </div>

            </div>


            <h4>
                Ordered Route Stops
            </h4>


            <div class="shared-driver-stops">
                ${stopsHtml}
            </div>


            <div class="shared-driver-actions">

                ${movementSection}

                <button
                    type="button"
                    class="btn btn-secondary"
                    onclick="loadActiveSharedRide()"
                >
                    Refresh
                </button>

            </div>

        </div>
    `;
}


// =========================================================
// Move Taxi One Step
// =========================================================

async function moveSharedTaxiNext() {

    const button = document.getElementById(
        "shared-move-next-button"
    );


    if (button) {

        button.disabled = true;

        button.textContent = (
            "Moving..."
        );
    }


    try {

        const response = await fetch(
            "/api/assignment/driver/shared-ride/move-next/",
            {
                method: "POST",

                credentials: "same-origin",

                headers: {
                    "Content-Type": "application/json",

                    "X-CSRFToken": (
                        getDriverCsrfToken()
                    ),
                },

                body: JSON.stringify({}),
            }
        );


        if (!response.ok) {

            const message = await getDriverApiError(
                response
            );

            alert(message);

            await loadActiveSharedRide();

            return;
        }


        const result = await response.json();


        // Useful while testing.
        console.log(
            "Shared movement result:",
            result
        );


        if (
            result.action === "RIDE_COMPLETED"
        ) {

            alert(
                "Shared ride completed."
            );

        } else if (
            result.action === "STOP_COMPLETED"
        ) {

            console.log(
                "Route stop completed:",
                result.completed_stop_id
            );

        } else {

            console.log(
                "Taxi moved to node:",
                result.current_node_id
            );
        }


        // Refresh current node + stop statuses.
        await loadActiveSharedRide();

        // Keep the operational map synchronized immediately.
        await refreshDriverMapIfAvailable();


    } catch (error) {

        console.error(error);

        alert(
            "Could not move the shared taxi."
        );


        await loadActiveSharedRide();
    }
}


// =========================================================
// Initial Load
// =========================================================

document.addEventListener(
    "DOMContentLoaded",
    () => {

        loadActiveSharedRide();

    }
);