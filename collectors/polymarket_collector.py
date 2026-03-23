"""
Polymarket Data Collector
Fetches prediction markets data
"""

import requests
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class PolymarketCollector:
    """
    Collect market data from Polymarket
    """
    
    def __init__(self):
        self.gamma_api = "https://gamma-api.polymarket.com"
        self.session = requests.Session()
    
    def search_weather_markets(self, location: str = None) -> List[Dict]:
        """
        Search for weather-related markets
        
        Returns list of markets with weather keywords
        """
        try:
            logger.info(f"🔍 Searching weather markets...")
            
            # Get all active markets
            url = f"{self.gamma_api}/markets"
            params = {
                'active': 'true',
                'limit': 100,
                'closed': 'false'
            }
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            all_markets = response.json()
            
            # Filter weather markets
            weather_keywords = [
                'rain', 'temperature', 'snow', 'weather',
                'celsius', 'fahrenheit', 'storm', 'precipitation',
                'degrees', 'cold', 'hot', 'freeze'
            ]
            
            weather_markets = []
            
            for market in all_markets:
                question = market.get('question', '').lower()
                
                # Check if question contains weather keywords
                if any(keyword in question for keyword in weather_keywords):
                    # Filter by location if specified
                    if location is None or location.lower() in question:
                        weather_markets.append(self._parse_market(market))
            
            logger.info(f"✅ Found {len(weather_markets)} weather markets")
            
            return weather_markets
            
        except Exception as e:
            logger.error(f"❌ Error fetching markets: {e}")
            return []
    
    def get_market(self, market_id: str) -> Optional[Dict]:
        """Get specific market by ID"""
        try:
            url = f"{self.gamma_api}/markets/{market_id}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            return self._parse_market(response.json())
            
        except Exception as e:
            logger.error(f"❌ Error fetching market {market_id}: {e}")
            return None
    
    def _parse_market(self, raw_market: Dict) -> Dict:
        """Parse raw market data into our format"""
        
        # Extract prices
        outcomes = raw_market.get('outcomes', [])
        yes_outcome = next((o for o in outcomes if o.lower() in ['yes', 'true']), None)
        no_outcome = next((o for o in outcomes if o.lower() in ['no', 'false']), None)
        
        # Get outcome prices (probabilities)
        outcome_prices = raw_market.get('outcomePrices', ['0.5', '0.5'])
        yes_price = float(outcome_prices[0]) if len(outcome_prices) > 0 else 0.5
        no_price = float(outcome_prices[1]) if len(outcome_prices) > 1 else 0.5
        
        # Parse end date
        end_date_str = raw_market.get('endDate', raw_market.get('end_date_iso'))
        end_date = None
        if end_date_str:
            try:
                end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
            except:
                pass
        
        return {
            'id': raw_market.get('id', raw_market.get('condition_id')),
            'question': raw_market.get('question', ''),
            'description': raw_market.get('description', ''),
            'category': raw_market.get('category', ''),
            'end_date': end_date,
            'yes_price': yes_price,
            'no_price': no_price,
            'volume': float(raw_market.get('volume', 0)),
            'liquidity': float(raw_market.get('liquidity', 0)),
            'active': raw_market.get('active', True),
            'url': f"https://polymarket.com/event/{raw_market.get('slug', '')}"
        }
    
    def extract_location_from_question(self, question: str) -> Optional[str]:
        """Extract city name from market question"""
        cities = [
            'New York', 'NYC', 'Chicago', 'Miami',
            'Los Angeles', 'LA', 'Seattle', 'Boston',
            'Dallas', 'Atlanta', 'San Francisco', 'Denver',
            'Washington', 'DC'
        ]
        
        question_lower = question.lower()
        
        for city in cities:
            if city.lower() in question_lower:
                return city
        
        return None
    
    def extract_date_from_question(self, question: str) -> Optional[str]:
        """
        Extract target date from question
        
        Returns YYYY-MM-DD or None
        """
        # Simple patterns
        tomorrow = datetime.now() + timedelta(days=1)
        today = datetime.now()
        
        question_lower = question.lower()
        
        if 'tomorrow' in question_lower:
            return tomorrow.strftime('%Y-%m-%d')
        elif 'today' in question_lower:
            return today.strftime('%Y-%m-%d')
        
        # TODO: More sophisticated date parsing
        
        return None
