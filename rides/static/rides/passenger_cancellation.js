(function () {
    "use strict";

    function csrfToken() {
        const input = document.querySelector(
            "[name=csrfmiddlewaretoken]"
        );

        if (input && input.value) {
            return input.value;
        }

        const cookie = document.cookie
            .split(";")
            .map((item) => item.trim())
            .find((item) => item.startsWith("csrftoken="));

        if (!cookie) {
            return "";
        }

        return decodeURIComponent(
            cookie.substring("csrftoken=".length)
        );
    }


    async function readResponse(response) {
        const contentType = (
            response.headers.get("content-type") || ""
        );

        if (contentType.includes("application/json")) {
            return await response.json();
        }

        return {
            detail: await response.text(),
        };
    }


    async function cancelRide(requestId) {
        const confirmed = window.confirm(
            "Cancel this ride request?\n\n" +
            "Cancellation is only allowed before your pickup."
        );

        if (!confirmed) {
            return;
        }

        const button = document.querySelector(
            `[data-cancel-request-id="${requestId}"]`
        );

        const originalText = (
            button ? button.textContent : ""
        );

        if (button) {
            button.disabled = true;
            button.textContent = "Cancelling...";
        }

        try {
            const response = await fetch(
                `/api/ride-requests/${requestId}/cancel/`,
                {
                    method: "POST",

                    credentials: "same-origin",

                    headers: {
                        "Accept": "application/json",
                        "X-CSRFToken": csrfToken(),
                    },
                }
            );

            const data = await readResponse(
                response
            );

            if (!response.ok) {
                throw new Error(
                    data.detail ||
                    "Ride request could not be cancelled."
                );
            }

            // Reload so:
            // - request status changes to CANCELLED
            // - tracking panel disappears
            // - shared/private route UI refreshes
            window.location.reload();

        } catch (error) {
            window.alert(
                error.message ||
                "Ride request could not be cancelled."
            );

            if (button) {
                button.disabled = false;
                button.textContent = originalText;
            }
        }
    }


    window.PassengerCancellation = {
        cancelRide,
    };
})();
