const DEFAULT_CENTER = [20.5937, 78.9629];

function escapeHtml(value) {
    return String(value || '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

function debounce(fn, wait) {
    let timer = null;
    return (...args) => {
        if (timer) {
            window.clearTimeout(timer);
        }
        timer = window.setTimeout(() => fn(...args), wait);
    };
}

async function geocodeAddress(query) {
    const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&addressdetails=1&limit=6&q=${encodeURIComponent(query)}`;
    const response = await fetch(url, {
        headers: {
            Accept: 'application/json',
        },
    });
    if (!response.ok) {
        return [];
    }
    const data = await response.json();
    return Array.isArray(data) ? data : [];
}

async function reverseGeocode(lat, lng) {
    const url = `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lng)}`;
    const response = await fetch(url, {
        headers: {
            Accept: 'application/json',
        },
    });
    if (!response.ok) {
        return '';
    }
    const data = await response.json();
    return data.display_name || '';
}

function haversineDistanceKm(aLat, aLng, bLat, bLng) {
    const toRad = (deg) => (deg * Math.PI) / 180;
    const r = 6371;
    const dLat = toRad(bLat - aLat);
    const dLng = toRad(bLng - aLng);
    const aa =
        Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos(toRad(aLat)) * Math.cos(toRad(bLat)) *
        Math.sin(dLng / 2) * Math.sin(dLng / 2);
    const c = 2 * Math.atan2(Math.sqrt(aa), Math.sqrt(1 - aa));
    return r * c;
}

function formatDuration(seconds) {
    const mins = Math.round(seconds / 60);
    if (mins < 60) {
        return `${mins} min`;
    }
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return `${h}h ${m}m`;
}

async function getRouteDistance(userLat, userLng, targetLat, targetLng) {
    const url = `https://router.project-osrm.org/route/v1/driving/${userLng},${userLat};${targetLng},${targetLat}?overview=false`;
    try {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error('Routing API unavailable');
        }
        const data = await response.json();
        const route = Array.isArray(data.routes) ? data.routes[0] : null;
        if (!route) {
            throw new Error('No route found');
        }
        return {
            mode: 'route',
            distanceKm: (route.distance || 0) / 1000,
            durationSec: route.duration || 0,
        };
    } catch {
        return {
            mode: 'direct',
            distanceKm: haversineDistanceKm(userLat, userLng, targetLat, targetLng),
            durationSec: null,
        };
    }
}

function initializePickupMap() {
    const mapEl = document.getElementById('pickupMap');
    if (!mapEl || typeof L === 'undefined') {
        return;
    }

    const latInput = document.getElementById('latitude');
    const lngInput = document.getElementById('longitude');
    const addressInput = document.getElementById('pickup_address');
    const suggestionsEl = document.getElementById('pickupAddressSuggestions');
    const hintEl = document.getElementById('pickupMapHint');
    const useMyLocationButton = document.getElementById('useMyLocation');

    const initialLat = Number.parseFloat(mapEl.dataset.lat || '');
    const initialLng = Number.parseFloat(mapEl.dataset.lng || '');

    const hasInitialCoords = Number.isFinite(initialLat) && Number.isFinite(initialLng);
    const center = hasInitialCoords ? [initialLat, initialLng] : DEFAULT_CENTER;
    const zoom = hasInitialCoords ? 14 : 5;

    const map = L.map(mapEl).setView(center, zoom);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);

    let marker = null;

    function updateCoordinates(lat, lng) {
        if (latInput) {
            latInput.value = lat.toFixed(6);
        }
        if (lngInput) {
            lngInput.value = lng.toFixed(6);
        }

        if (!marker) {
            marker = L.marker([lat, lng]).addTo(map);
        } else {
            marker.setLatLng([lat, lng]);
        }
    }

    function renderSuggestions(items) {
        if (!suggestionsEl) {
            return;
        }

        suggestionsEl.innerHTML = '';
        if (!items.length) {
            suggestionsEl.classList.add('hidden');
            return;
        }

        items.forEach((item) => {
            const lat = Number.parseFloat(item.lat);
            const lng = Number.parseFloat(item.lon);
            if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
                return;
            }

            const option = document.createElement('button');
            option.type = 'button';
            option.textContent = item.display_name || `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
            option.addEventListener('click', () => {
                if (addressInput) {
                    addressInput.value = item.display_name || addressInput.value;
                }
                map.setView([lat, lng], 16);
                updateCoordinates(lat, lng);
                suggestionsEl.classList.add('hidden');
                if (hintEl) {
                    hintEl.textContent = 'Address selected and map pin updated.';
                }
            });
            suggestionsEl.appendChild(option);
        });

        suggestionsEl.classList.remove('hidden');
    }

    const searchAddress = debounce(async () => {
        if (!addressInput || !suggestionsEl) {
            return;
        }
        const query = addressInput.value.trim();
        if (query.length < 3) {
            suggestionsEl.classList.add('hidden');
            suggestionsEl.innerHTML = '';
            return;
        }
        const results = await geocodeAddress(query);
        renderSuggestions(results);
    }, 300);

    if (addressInput) {
        addressInput.addEventListener('input', searchAddress);
        addressInput.addEventListener('blur', () => {
            window.setTimeout(() => {
                if (suggestionsEl) {
                    suggestionsEl.classList.add('hidden');
                }
            }, 150);
        });
    }

    if (hasInitialCoords) {
        updateCoordinates(initialLat, initialLng);
    }

    map.on('click', async (event) => {
        updateCoordinates(event.latlng.lat, event.latlng.lng);
        if (addressInput) {
            const addr = await reverseGeocode(event.latlng.lat, event.latlng.lng);
            if (addr) {
                addressInput.value = addr;
            }
        }
        if (hintEl) {
            hintEl.textContent = 'Pin moved on map. Address auto-updated when available.';
        }
    });

    if (useMyLocationButton) {
        useMyLocationButton.addEventListener('click', () => {
            if (!navigator.geolocation) {
                window.alert('Geolocation is not supported in your browser.');
                return;
            }

            navigator.geolocation.getCurrentPosition(
                (position) => {
                    const lat = position.coords.latitude;
                    const lng = position.coords.longitude;
                    map.setView([lat, lng], 14);
                    updateCoordinates(lat, lng);
                    if (addressInput) {
                        reverseGeocode(lat, lng).then((addr) => {
                            if (addr) {
                                addressInput.value = addr;
                            }
                        });
                    }
                },
                () => {
                    window.alert('Unable to fetch your location. Please click on the map manually.');
                }
            );
        });
    }
}

function initializeListingsMap(mapElementId, dataElementId) {
    const mapEl = document.getElementById(mapElementId);
    const dataEl = document.getElementById(dataElementId);

    if (!mapEl || !dataEl || typeof L === 'undefined') {
        return;
    }

    let listings = [];
    try {
        listings = JSON.parse(dataEl.textContent || '[]');
    } catch {
        listings = [];
    }

    const map = L.map(mapEl).setView(DEFAULT_CENTER, 5);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);

    const distanceInfoEl = document.getElementById(
        mapElementId === 'ngoListingsMap' ? 'ngoDistanceInfo' : 'donorDistanceInfo'
    );

    let userMarker = null;
    let userLat = null;
    let userLng = null;

    function setDistanceInfo(message) {
        if (distanceInfoEl) {
            distanceInfoEl.textContent = message;
        }
    }

    function locateUser() {
        if (!navigator.geolocation) {
            setDistanceInfo('Geolocation not supported in this browser.');
            return;
        }

        navigator.geolocation.getCurrentPosition(
            (position) => {
                userLat = position.coords.latitude;
                userLng = position.coords.longitude;

                if (!userMarker) {
                    userMarker = L.circleMarker([userLat, userLng], {
                        radius: 8,
                        color: '#0ea5e9',
                        fillColor: '#0ea5e9',
                        fillOpacity: 0.8,
                    }).addTo(map);
                    userMarker.bindPopup('Your current location');
                } else {
                    userMarker.setLatLng([userLat, userLng]);
                }

                setDistanceInfo('Your live location is active. Click any listing marker for distance and ETA.');
            },
            () => {
                setDistanceInfo('Location permission denied. Enable location to view distance and ETA.');
            }
        );
    }

    locateUser();

    const markers = [];

    listings.forEach((item) => {
        const lat = Number.parseFloat(item.latitude);
        const lng = Number.parseFloat(item.longitude);
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
            return;
        }

        const marker = L.marker([lat, lng]).addTo(map);
        const donationPrice = Number.isFinite(Number(item.donation_price))
            ? `Rs. ${Number(item.donation_price).toFixed(2)}`
            : 'Rs. 0.00';
        const pickupAddress = item.pickup_address || item.location || 'Address not available';

        marker.bindPopup(`
            <div style="min-width:180px">
                <strong>${escapeHtml(item.food_name || 'Listing')}</strong><br>
                Qty: ${escapeHtml(item.quantity || 0)}<br>
                Price: ${escapeHtml(donationPrice)}<br>
                Status: ${escapeHtml(item.status || 'available')}<br>
                ${escapeHtml(pickupAddress)}
            </div>
        `);

        marker.on('click', async () => {
            if (!Number.isFinite(userLat) || !Number.isFinite(userLng)) {
                setDistanceInfo('Enable location to calculate distance and ETA.');
                return;
            }

            const route = await getRouteDistance(userLat, userLng, lat, lng);
            const distanceText = `${route.distanceKm.toFixed(2)} km`;
            if (route.mode === 'route' && route.durationSec) {
                setDistanceInfo(`Distance to ${item.food_name}: ${distanceText} | ETA: ${formatDuration(route.durationSec)}`);
            } else {
                setDistanceInfo(`Approx direct distance to ${item.food_name}: ${distanceText} (route ETA unavailable)`);
            }
        });

        markers.push(marker);
    });

    if (markers.length > 0) {
        const group = L.featureGroup(markers);
        map.fitBounds(group.getBounds().pad(0.2));
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initializePickupMap();
    initializeListingsMap('ngoListingsMap', 'ngoListingsData');
    initializeListingsMap('donorListingsMap', 'donorListingsData');
});
