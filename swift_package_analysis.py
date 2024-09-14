import requests
import os
import time
import json
import pandas as pd

# GitHub API token from GitHub Actions environment variable
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
headers = {'Authorization': f'token {GITHUB_TOKEN}'}

# Load checkpoint if it exists
checkpoint_file = 'results/checkpoint.json'
try:
    with open(checkpoint_file, 'r') as f:
        checkpoint_data = json.load(f)
except FileNotFoundError:
    checkpoint_data = {'processed_repos': []}

# GitHub search URL to find repositories with a Package.swift file
search_url = "https://api.github.com/search/repositories?q=Package.swift+language:swift"

# Fetch repositories with a Package.swift file
def fetch_repositories(page=1):
    response = requests.get(f"{search_url}&page={page}", headers=headers)
    if response.status_code != 200:
        raise Exception(f"GitHub API error: {response.status_code}")
    return response.json()

# Handle rate limit
def check_rate_limit():
    rate_limit_url = "https://api.github.com/rate_limit"
    response = requests.get(rate_limit_url, headers=headers)
    rate_data = response.json()
    remaining = rate_data['rate']['remaining']
    reset_time = rate_data['rate']['reset']
    
    if remaining < 5:  # If close to rate limit, wait for reset
        wait_time = reset_time - time.time()
        if wait_time > 0:
            print(f"Rate limit reached. Waiting {wait_time} seconds.")
            time.sleep(wait_time)

# Parse the Package.swift file to extract dependencies and versions
def parse_package_swift(repo_name, repo_url):
    package_url = f"https://raw.githubusercontent.com/{repo_name}/main/Package.swift"
    response = requests.get(package_url, headers=headers)

    if response.status_code == 200:
        package_data = response.text
        dependencies = extract_dependencies(package_data, repo_name)
        return dependencies
    else:
        print(f"Failed to retrieve Package.swift for {repo_name}")
        return []

# Extract dependencies from the Package.swift file
def extract_dependencies(package_data, repo_name):
    dependencies = []

    # The format of Package.swift includes the list of dependencies in Swift's native format
    # We'll do a basic string search for now. You can improve this with a more robust parser.
    start_key = ".package("
    end_key = "),"
    
    package_lines = package_data.splitlines()
    for line in package_lines:
        if start_key in line:
            # Extract URL and version info
            url_start = line.find("url:") + 5
            url_end = line.find(",", url_start)
            version_start = line.find("from:") + 6
            version_end = line.find(")", version_start)

            package_url = line[url_start:url_end].replace('"', '').strip()
            version = line[version_start:version_end].replace('"', '').strip()

            dependencies.append({
                'package_url': package_url,
                'version': version,
                'repo_name': repo_name
            })
    return dependencies

# Recursively fetch and analyze sub-dependencies
def fetch_sub_dependencies(package_url, depth=0):
    # Stop after a certain depth to avoid endless recursion
    if depth > 3:
        return []

    # Analyze the dependencies of the sub-dependency
    repo_name = package_url.replace("https://github.com/", "")
    return parse_package_swift(repo_name, package_url)

# Save progress in the checkpoint file
def save_checkpoint(processed_repos):
    checkpoint_data['processed_repos'] = processed_repos
    with open(checkpoint_file, 'w') as f:
        json.dump(checkpoint_data, f)

# Main function to process repositories and analyze their dependencies
def process_repositories():
    page = 1
    processed_repos = checkpoint_data['processed_repos']
    all_data = []
    dependency_graph = []  # To store dependency relationships

    while True:
        check_rate_limit()  # Check rate limits before each page request
        repo_data = fetch_repositories(page)
        
        # Stop if no more repositories
        if not repo_data['items']:
            break
        
        for repo in repo_data['items']:
            repo_name = repo['full_name']
            if repo_name in processed_repos:
                print(f"Skipping {repo_name}, already processed.")
                continue

            print(f"Processing {repo_name}...")

            # Fetch and analyze dependencies
            dependencies = parse_package_swift(repo_name, repo['html_url'])
            for dep in dependencies:
                # Fetch sub-dependencies for each dependency
                sub_deps = fetch_sub_dependencies(dep['package_url'], depth=1)
                dep['sub_dependencies'] = sub_deps
                dependency_graph.append(dep)

            repo_info = {
                'name': repo['name'],
                'url': repo['html_url'],
                'stars': repo['stargazers_count'],
                'last_commit': repo['updated_at'],
                'dependencies': dependencies
            }
            all_data.append(repo_info)

            processed_repos.append(repo_name)  # Add to processed list
            save_checkpoint(processed_repos)  # Save progress to checkpoint

        page += 1  # Go to the next page of repositories

    # Save results to CSV
    df_repos = pd.DataFrame(all_data)
    df_repos.to_csv('results/swift_package_results.csv', index=False)
    
    df_deps = pd.DataFrame(dependency_graph)
    df_deps.to_csv('results/swift_package_dependencies.csv', index=False)

    print("Data saved to results/swift_package_results.csv and swift_package_dependencies.csv")

if __name__ == "__main__":
    process_repositories()