"""
NOAA Weather Data Collector
Fetches official weather forecasts - FREE API!
"""

import requests
import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class NOAACollector:
    """
    Collect weather forecasts from NOAA API
    No API key required!
    """
    
    def __init__(self):
        self.base_url = "https://api.weather.gov"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': '(PolymarketWeatherBot, contact@example.com)'
        })
    
    # Major US city coordinates
    CITY_COORDS = {
        'new york': (40.7128, -74.0060),
        'nyc': (40.7128, -74.0060),
        'chicago': (41.8781, -87.6298),
        'miami': (25.7617, -80.1918),
        'los angeles': (34.0522, -118.2437),
        'la': (34.0522, -118.2437),
        'seattle': (47.6062, -122.3321),
        'boston': (42.3601, -71.0589),
        'dallas': (32.7767, -96.7970),
        'atlanta': (33.7490, -84.3880),
        'san francisco': (37.7749, -122.4194),
        'denver': (39.7392, -104.9903),
        'washington': (38.9072, -77.0369),
        'dc': (38.9072, -77.0369),
    }
    
    def get_coordinates(self, location: str) -> tuple:
        """Get coordinates for city name"""
        location_lower = location.lower().strip()
        
        if location_lower in self.CITY_COORDS:
            return self.CITY_COORDS[location_lower]
        else:
            logger.warning(f"Location {location} not found, using NYC")
            return self.CITY_COORDS['nyc']
    
    def get_forecast(self, location: str) -> Optional[Dict]:
        """
        Get weather forecast for location
        
        Returns:
        {
            'location': 'New York',
            'forecasts': [
                {
                    'date': '2026-03-24',
                    'rain_probability': 85,
                    'temperature_high': 72,
                    'temperature_low': 58,
                    'conditions': 'Thunderstorms'
                }
            ]
        }
        """
        try:
            lat, lon = self.get_coordinates(location)
            logger.info(f"📡 Fetching forecast for {location} ({lat}, {lon})")
            
            # Get forecast URL
            points_url = f"{self.base_url}/points/{lat},{lon}"
            response = self.session.get(points_url, timeout=10)
            response.raise_for_status()
            
            forecast_url = response.json()['properties']['forecast']
            
            # Get forecast data
            forecast_response = self.session.get(forecast_url, timeout=10)
            forecast_response.raise_for_status()
            
            forecast_data = forecast_response.json()
            forecasts = self._parse_forecast(forecast_data)
            
            logger.info(f"✅ Got {len(forecasts)} forecast periods for {location}")
            
            return {
                'location': location,
                'latitude': lat,
                'longitude': lon,
                'forecasts': forecasts,
                'retrieved_at': datetime.utcnow().isoformat(),
                'source': 'NOAA'
            }
            
        except Exception as e:
            logger.error(f"❌ NOAA API error for {location}: {e}")
            return None
    
    def _parse_forecast(self, data: Dict) -> List[Dict]:
        """Parse NOAA forecast periods"""
        forecasts = []
        periods = data['properties']['periods']
        
        for i in range(0, min(len(periods), 14), 2):  # Next 7 days
            day_period = periods[i]
            night_period = periods[i+1] if i+1 < len(periods) else None
            
            # Extract date
            start_time = day_period['startTime']
            forecast_date = start_time[:10]  # YYYY-MM-DD
            
            # Get rain probability
            rain_prob = day_period.get('probabilityOfPrecipitation', {}).get('value', 0) or 0
            
            # Get temperature
            temp_high = day_period.get('temperature', 0)
            temp_low = night_period.get('temperature', 0) if night_period else 0
            
            # Get conditions
            conditions = day_period.get('shortForecast', 'Unknown')
            
            forecasts.append({
                'date': forecast_date,
                'rain_probability': rain_prob,
                'temperature_high': temp_high,
                'temperature_low': temp_low,
                'conditions': conditions,
                'detailed': day_period.get('detailedForecast', '')
            })
        
        return forecasts
    
    def get_rain_probability(self, location: str, target_date: str) -> Optional[float]:
        """
        Get rain probability for specific date
        
        Args:
            location: City name
            target_date: YYYY-MM-DD format
            
        Returns:
            Rain probability (0-100) or None
        """
        forecast = self.get_forecast(location)
        
        if not forecast:
            return None
        
        for period in forecast['forecasts']:
            if period['date'] == target_date:
                return period['rain_probability']
        
        return None
