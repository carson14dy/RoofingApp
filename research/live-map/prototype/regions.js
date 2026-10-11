'use strict';

// Public town-center samples for navigation, not geocoded roofs or instruments.
const WEATHER_REGIONS = Object.freeze({
  montana: {
    id: 'montana',
    label: 'Montana',
    timeZone: 'America/Denver',
    stateFips: '30',
    center: [46.8, -110.3],
    zoom: 6,
    bounds: [[44.35, -116.1], [49.01, -104.03]],
    sampleSites: [
      {id: 'billings', label: 'Billings', lat: 45.7833, lon: -108.5007},
      {id: 'missoula', label: 'Missoula', lat: 46.8721, lon: -113.9940},
      {id: 'kalispell', label: 'Kalispell', lat: 48.19199, lon: -114.31681},
      {id: 'great-falls', label: 'Great Falls', lat: 47.5053, lon: -111.3008},
      {id: 'helena', label: 'Helena', lat: 46.5891, lon: -112.0391},
      {id: 'bozeman', label: 'Bozeman', lat: 45.6770, lon: -111.0429},
      {id: 'butte', label: 'Butte', lat: 46.0038, lon: -112.5348},
      {id: 'havre', label: 'Havre', lat: 48.55, lon: -109.6841},
      {id: 'lewistown', label: 'Lewistown', lat: 47.0625, lon: -109.4282},
      {id: 'glasgow', label: 'Glasgow', lat: 48.19696, lon: -106.6367},
      {id: 'miles-city', label: 'Miles City', lat: 46.4083, lon: -105.8406},
      {id: 'glendive', label: 'Glendive', lat: 47.1053, lon: -104.7125},
      {id: 'west-yellowstone', label: 'West Yellowstone', lat: 44.6621, lon: -111.1041}
    ],
    locationNote: 'Town samples are public map reference points, not roof measurements. Choose a town, click anywhere on the map, or enter coordinates.',
    terrainNote: 'Across Montana, mountain terrain, elevation changes and instrument exposure can make a nearby station unrepresentative of your site. Forecast grids and radar sampling also have terrain limits.'
  },
  'kansas-city': {
    id: 'kansas-city',
    label: 'Kansas City',
    timeZone: 'America/Chicago',
    stateFips: null,
    center: [39.0997, -94.5786],
    zoom: 8,
    bounds: null,
    sampleSites: [
      {id: 'downtown-kansas-city', label: 'Downtown Kansas City', lat: 39.0997, lon: -94.5786}
    ],
    locationNote: 'The downtown Kansas City sample is a public map reference point, not a roof measurement. Click the map or enter coordinates.',
    terrainNote: 'Nearby station readings depend on instrument exposure and distance. Weather at a roof can differ from a station observation or forecast grid.'
  }
});
