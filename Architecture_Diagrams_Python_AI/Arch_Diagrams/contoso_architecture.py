"""
Azure Architecture Diagram Generator for Contoso Medical Portal
Generates PNG, DOT, and Draw.io format diagrams
"""

import subprocess
from diagrams import Diagram, Cluster, Edge
from diagrams.azure.compute import AppServices, FunctionApps
from diagrams.azure.network import (
    VirtualNetworks, ApplicationGateway, FrontDoors,
    NetworkSecurityGroupsClassic, Firewall, RouteTables
)
from diagrams.azure.database import SQLServers, SQLDatabases
from diagrams.azure.storage import StorageAccounts
from diagrams.azure.security import KeyVaults
from diagrams.azure.integration import ServiceBus
from diagrams.azure.analytics import LogAnalyticsWorkspaces
from diagrams.azure.devops import ApplicationInsights
from diagrams.onprem.client import Users

# Graph attributes for clean layout
graph_attr = {
    "splines": "ortho",
    "nodesep": "0.8",
    "ranksep": "1.2",
    "fontsize": "14",
    "bgcolor": "white",
    "pad": "0.5",
    "compound": "true"
}

# Cluster attributes for different tiers
vnet_cluster_attr = {
    "fontsize": "14",
    "bgcolor": "#E8F4F8",
    "style": "dashed",
    "margin": "25"
}

frontend_cluster_attr = {
    "fontsize": "13",
    "bgcolor": "#E3F2FD",
    "style": "rounded",
    "margin": "15"
}

backend_cluster_attr = {
    "fontsize": "13",
    "bgcolor": "#F3E5F5",
    "style": "rounded",
    "margin": "15"
}

data_cluster_attr = {
    "fontsize": "13",
    "bgcolor": "#FFF3E0",
    "style": "rounded",
    "margin": "15"
}

firewall_cluster_attr = {
    "fontsize": "13",
    "bgcolor": "#FFEBEE",
    "style": "rounded",
    "margin": "15"
}

monitoring_cluster_attr = {
    "fontsize": "13",
    "bgcolor": "#E8F5E9",
    "style": "rounded",
    "margin": "15"
}

# Create the diagram
with Diagram(
    "Contoso Medical Portal Architecture",
    filename="diagrams/contoso_architecture",
    outformat=["png", "dot"],
    show=False,
    direction="TB",
    graph_attr=graph_attr
):
    
    # External users
    users = Users("Users")
    
    # Front Door (external to VNet)
    afd = FrontDoors("afd-contoso\n(Azure Front Door)")
    
    # VNet container with all internal resources
    with Cluster("vnet-contoso-auea-001\n(10.10.0.0/16)", graph_attr=vnet_cluster_attr):
        
        # Frontend Subnet
        with Cluster("snet-frontend\n(10.10.1.0/24)", graph_attr=frontend_cluster_attr):
            nsg_frontend = NetworkSecurityGroupsClassic("NSG-Frontend")
            agw = ApplicationGateway("agw-contoso\n(WAF)")
            webapp = AppServices("app-frontend-portal\n(Web App)")
        
        # Backend Subnet
        with Cluster("snet-backend\n(10.10.2.0/24)", graph_attr=backend_cluster_attr):
            nsg_backend = NetworkSecurityGroupsClassic("NSG-Backend")
            backend_api = AppServices("app-order-api\n(Backend API)")
            func_app = FunctionApps("func-order-processor\n(Function App)")
            service_bus = ServiceBus("sb-contoso-orders\n(Service Bus)")
        
        # Data Subnet
        with Cluster("snet-data\n(10.10.3.0/24)", graph_attr=data_cluster_attr):
            nsg_data = NetworkSecurityGroupsClassic("NSG-Data")
            sql_server = SQLServers("sqlsrv-contoso")
            sql_db = SQLDatabases("sqldb-orders")
            storage = StorageAccounts("stcontosodata001")
            keyvault = KeyVaults("kv-contoso-prod")
        
        # Firewall (separate area)
        with Cluster("Firewall & Routing", graph_attr=firewall_cluster_attr):
            azfw = Firewall("azfw-contoso\n(Azure Firewall)")
            route_table = RouteTables("Route Table\n(Default to FW)")
    
    # Monitoring (external to VNet)
    with Cluster("Monitoring", graph_attr=monitoring_cluster_attr):
        law = LogAnalyticsWorkspaces("law-contoso-prod\n(Log Analytics)")
        appi = ApplicationInsights("appi-contoso\n(App Insights)")
    
    # Connection flows
    # User traffic flow
    users >> Edge(label="HTTPS") >> afd
    afd >> Edge(label="HTTPS") >> agw
    agw >> Edge(label="HTTPS") >> webapp
    
    # Web app to backend
    webapp >> Edge(label="API") >> backend_api
    
    # Backend to data tier
    backend_api >> Edge(label="SQL\n(Private)") >> sql_db
    backend_api >> Edge(label="Storage\n(Private)") >> storage
    
    # Function app flows
    func_app >> Edge(label="Message") >> service_bus
    service_bus >> Edge(label="Process") >> func_app
    func_app >> Edge(label="SQL\n(Private)") >> sql_db
    
    # Key Vault connections
    webapp >> Edge(label="Secrets", style="dotted") >> keyvault
    backend_api >> Edge(label="Secrets", style="dotted") >> keyvault
    func_app >> Edge(label="Secrets", style="dotted") >> keyvault
    
    # SQL Server to Database
    sql_server >> Edge(label="hosts") >> sql_db
    
    # Firewall routing
    webapp >> Edge(label="Outbound", style="dashed") >> azfw
    backend_api >> Edge(label="Outbound", style="dashed") >> azfw
    func_app >> Edge(label="Outbound", style="dashed") >> azfw
    
    # Monitoring connections
    webapp >> Edge(label="Logs", style="dotted", color="green") >> law
    backend_api >> Edge(label="Logs", style="dotted", color="green") >> law
    func_app >> Edge(label="Logs", style="dotted", color="green") >> law
    sql_db >> Edge(label="Logs", style="dotted", color="green") >> law
    storage >> Edge(label="Logs", style="dotted", color="green") >> law
    
    webapp >> Edge(label="Telemetry", style="dotted", color="green") >> appi
    backend_api >> Edge(label="Telemetry", style="dotted", color="green") >> appi
    func_app >> Edge(label="Telemetry", style="dotted", color="green") >> appi

print("✓ PNG and DOT files generated in diagrams/")

# Convert DOT to Draw.io format
try:
    subprocess.run([
        "graphviz2drawio", 
        "diagrams/contoso_architecture.dot", 
        "-o", 
        "diagrams/contoso_architecture.drawio"
    ], check=True)
    print("✓ Draw.io file generated: diagrams/contoso_architecture.drawio")
except subprocess.CalledProcessError as e:
    print(f"✗ Failed to convert to Draw.io format: {e}")
except FileNotFoundError:
    print("✗ graphviz2drawio not found. Install with: pip install graphviz2drawio")

print("\nGenerated files:")
print("  - diagrams/contoso_architecture.png")
print("  - diagrams/contoso_architecture.dot")
print("  - diagrams/contoso_architecture.drawio")
