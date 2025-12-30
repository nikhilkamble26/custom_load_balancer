import httpx
import itertools
import time
from openai import AzureOpenAI, APIError

class LoadBalancerTransport(httpx.AsyncBaseTransport):
    """
    An asynchronous HTTP transport that load balances requests across multiple endpoints.
    """
    def __init__(self, endpoints):
        self.endpoints = endpoints
        # Use an iterator to cycle through endpoints for round-robin
        self.endpoint_iterator = itertools.cycle(self.endpoints)
        self.backoff_times = {} # To store cooldown periods for throttled endpoints

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        for _ in range(len(self.endpoints)):
            endpoint = next(self.endpoint_iterator)
            
            # Check if endpoint is in cooldown
            if endpoint in self.backoff_times and time.time() < self.backoff_times[endpoint]:
                continue

            # Modify the request URL to target the selected backend endpoint
            original_url = str(request.url)
            new_url = original_url.replace(str(request.url.host), endpoint['host'])
            request.url = httpx.URL(new_url)

            # Add required API key in header (if using API key auth)
            # This logic depends on how your endpoints are configured
            request.headers['api-key'] = endpoint['api_key'] 

            try:
                # Use a default transport to send the actual request
                response = await httpx.AsyncHTTPTransport().handle_async_request(request)
                
                if response.status_code == 429:
                    # Handle throttling: put endpoint on cooldown
                    retry_after = int(response.headers.get("Retry-After", 60)) # Default to 60s
                    self.backoff_times[endpoint] = time.time() + retry_after
                    print(f"Endpoint {endpoint['host']} throttled. Retrying another endpoint.")
                    continue # Try the next endpoint
                
                return response
            except httpx.RequestError as e:
                print(f"Request to {endpoint['host']} failed: {e}. Retrying another endpoint.")
                continue
        
        # If all endpoints fail or are throttling
        raise APIError("All endpoints are unavailable or throttling.")

# --- Usage Example ---
endpoints = [
    {"host": "aoai-instance-eastus.openai.azure.com", "api_key": "key1"},
    {"host": "aoai-instance-westus.openai.azure.com", "api_key": "key2"},
]

# Instantiate the load balancer transport
lb_transport = LoadBalancerTransport(endpoints)

# Inject the load balancer transport into the AsyncAzureOpenAI client
# The base_url needs to be seeded, but the host will be overridden by the transport logic
client = AsyncAzureOpenAI(
    azure_endpoint=f"https://{endpoints[0]['host']}", 
    api_version="2023-12-01-preview",
    api_key="does-not-matter", # Overridden by transport
    http_client=httpx.AsyncClient(transport=lb_transport)
)

async def main():
    try:
        response = await client.chat.completions.create(
            model="your-deployment-name",
            messages=[{"role": "system", "content": "You are a helpful assistant."}],
        )
        print(response.choices[0].message.content)
    except Exception as e:
        print(f"An error occurred: {e}")

# Run the async main function
# import asyncio
# asyncio.run(main())
